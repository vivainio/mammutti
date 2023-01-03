import argparse
import os.path
import os.path
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Dict, Any
from xml.etree.ElementTree import ParseError
import re

from pydantic import BaseModel
from yaml import dump

from . import msbuildutil
from .xml_appconfig import Tags
from .xml_csproj import Tags as CsProjTags

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper


def xget(parent, name):
    node = parent.find(name)
    return node.attrib


class Redirect(BaseModel):
    lib: str
    to_ver: str
    extra: Optional[str]


class AppConfig(BaseModel):
    path: str
    redirects: List[Redirect]


def parse_xml_and_drop_ns(fname):
    # instead of ET.fromstring(xml)
    try:
        it = ET.iterparse(fname)

        for _, el in it:
            _, _, el.tag = el.tag.rpartition('}')  # strip ns
        root = it.root
        return root
    except ParseError as e:
        # print("Broken xml ", fname, e)
        return None


def parse_app_config(fname: str):
    try:
        parsed = ET.parse(fname)
    except ParseError as e:
        # print("Broken xml ", fname, e)
        return None

    redirs = []
    for i in parsed.iter(Tags.dependentAssembly):
        id = xget(i, Tags.assemblyIdentity)["name"]
        redir = xget(i, Tags.bindingRedirect)["newVersion"]
        redirs.append(Redirect(lib=id, to_ver=redir, extra=None))

    return AppConfig(
        path=str(fname),
        redirects=sorted(redirs, key=lambda r: r.lib)
    )


class Reference(BaseModel):
    name: str
    hintpath: Optional[str]
    # we can add more extra shit here, e.g. Paket, publickey
    tags: Optional[str]


class CsProj(BaseModel):
    path: str
    name: str
    props: Dict[str, Optional[str]]
    prjrefs: List[str]
    refs: List[Reference]
    outputpath: str
    errors: Optional[List[Any]]
    home: str

    def add_error(self, error: Any):
        if not self.errors:
            self.errors = []
        self.errors.append(error)



def extract_property_groups(parsed: ET.Element):
    props = {}
    for pg in parsed.iter(CsProjTags.PropertyGroup):
        for prop in pg.iter():
            props[prop.tag] = prop.text and prop.text.strip()
    return props


class Ws:
    def __init__(self, root: str):
        self.root = Path(root)
        self.all = [s.decode() for s in
                    subprocess.run("git ls-files", capture_output=True, cwd=root).stdout.splitlines()]

        self.msbuild_props = {}

    def prune(self, pats: List[str]):
        def prune_it(s):
            for pat in pats:
                if re.search(pat, s):
                    return True

            return False

        self.all = [f for f in self.all if not prune_it(f)]
        

    def configs(self):
        return self.by_ext(".config")

    def by_ext(self, ext):
        return [f for f in self.all if f.endswith(ext)]

    def read_msbuild_variables(self):
        propsfiles = [p for p in self.all if p.lower() == "directory.build.props"]
        if propsfiles:
            parsed = ET.parse(self.root / propsfiles[0])
            oprops = extract_property_groups(parsed)
            props = {k.lower():v for (k,v) in oprops.items()}
            thisdir = os.path.dirname(propsfiles[0])
            props["MSBuildThisFileDirectory".lower()] = thisdir if thisdir else "."
            msbuildutil.expand_recursive(props)
            # store everything in lower case since these are case insensitive
            self.msbuild_props.update({
                k.lower(): self.to_rel(v) for (k,v) in props.items()
            })

    def resolve_path(self, path):
        path = msbuildutil.expand_variables(path, self.msbuild_props)
        return path.replace("\\", "/")

    def collect_redirects(self):
        found = {}

        for c in self.configs():
            parsed = parse_app_config(self.root / c)
            if not parsed:
                continue
            parsed.path = c

            for r in parsed.redirects:
                key = f"{r.lib} {r.to_ver}"
                found.setdefault(key, []).append(str(parsed.path))

        return found

    def analyze_redirects(self):
        coll = self.collect_redirects()
        print("Outlier binding redirects")
        for k, v in coll.items():
            if len(v) < 3:
                print(k, str(v))

    def to_rel(self, pth):
        """ take any path, return normalized relative path """

        # with variable declarations, don't touch it
        pth = str(pth)
        pth = self.resolve_path(pth)
        abs = (self.root / pth).resolve()
        return os.path.relpath(abs, self.root).replace("\\", "/")

    def to_rel_join(self, prjroot, fname):
        if fname.startswith("$("):
            return self.resolve_path(fname)
        return self.to_rel(prjroot / fname)

    def check_csprojs(self, projs: List[CsProj]):
        for parsed in projs:
            for prjref in parsed.prjrefs:
                if not prjref in self.all:
                    if not parsed.errors:
                        parsed.errors = []
                    parsed.add_error(f"Bad project reference: {prjref}")

        # check for paket use
        for parsed in projs:
            for ref in parsed.refs:
                if ref.hintpath and "packages" in ref.hintpath:
                    if not ref.tags or "paket" not in ref.tags:
                        parsed.add_error(f"no_paket: Should use Paket: {ref.hintpath}")
                if ref.hintpath and ref.hintpath.startswith(".."):
                    parsed.add_error("abs_hintpath: HintPath points outside repository: "+ ref.hintpath)

        self.check_canonical_refs(projs)

    def collect_modules(self):
        """ collect modules """

        self.read_msbuild_variables()
        files = self.by_ext(".csproj")
        res = []
        for f in files:
            path = self.root / f
            parsed = self.parse_csproj(path)
            if not parsed:
                continue
            res.append(parsed)

        self.check_csprojs(res)
        return res

    def dump_modules(self):
        c = self.collect_modules()
        for m in c:
            print(m.name + ":")
            print("  OutputPath: " + m.outputpath)
            if m.errors:
                print("  Errors:")
                for e in m.errors:
                    print(f"    - {e}")

            # if m.refs:
            #    print(f"  References: {m.refs}")

    def check_canonical_refs(self, csprojs: List[CsProj]):
        homes = {
            p.name: p.home for p in csprojs
        }

        for p in csprojs:
            for r in p.refs:
                should_be = homes.get(r.name)
                if not should_be:
                    continue

                # outputpath can be used instead of hintpath if hintpath is missing
                but_is = r.hintpath or self.to_rel_join(Path(p.outputpath), r.name+".dll")
                if should_be != but_is:
                    p.add_error(f"bad_dll_ref: Noncanonical dll ref, should_be={should_be}, but_is={but_is}")

    def parse_csproj(self, fname: Path):
        parsed = parse_xml_and_drop_ns(fname)
        if not parsed:
            return None
        prjroot = fname.parent
        project_refs = []
        props = extract_property_groups(parsed)

        for pref in parsed.iter(CsProjTags.ProjectReference):
            p = pref.attrib["Include"]
            project_refs.append(self.to_rel(prjroot / p))

        ass_name = props.get("AssemblyName") or Path(fname).stem

        outputpath = None
        op = props.get("OutputPath")
        if op:
            if "$(" in op:
                outputpath = self.resolve_path(op)
            else:
                outputpath = self.to_rel((fname.parent / op).resolve())

        refs = []
        errors = []
        for ref in parsed.iter(CsProjTags.Reference):
            name = ref.attrib["Include"].split(",")[0]
            hintpath = list(ref.iter(CsProjTags.HintPath))
            hp = None
            if hintpath:
                htext = hintpath[0].text
                hp = self.to_rel_join(prjroot, htext)

            paket = list(ref.iter("Paket"))
            if paket:
                tags = "paket"
            else:
                tags = None

            r = Reference(name=name, hintpath=hp, tags=tags)

            refs.append(r)
        ret = CsProj(
            path=self.to_rel(fname),
            name=ass_name,
            props=props,
            prjrefs=project_refs,
            refs=refs,
            outputpath=outputpath or "",
            errors=None,
            home=f"{outputpath}/{ass_name}.dll"
        )
        if errors:
            ret.errors = errors

        return ret


class ModulesReport(BaseModel):
    modules: List[CsProj]

def strip_to_errors(modules: List[CsProj]):
    res = []
    for m in modules:
        if not m.errors:
            continue
        m.props = {}
        m.refs = []
        m.prjrefs = []
        res.append(m)

    return res



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--errors", action="store_true", help="Only list modules with errors, strip details")
    parser.add_argument("--prune", action="append", help="Add regex pattern to prune projecs with certain full paths")
    parser.add_argument("rootdir", help="Repository root directory")
    parsed = parser.parse_args()
    ws = Ws(parsed.rootdir)

    ws.prune(parsed.prune)
    modules = ws.collect_modules()
    if parsed.errors:
        modules = strip_to_errors(modules)
    rep = ModulesReport(modules=modules)
    modules = rep.dict(exclude_none=True, )["modules"]
    by_module = sorted(((m["name"], m) for m in modules), key=lambda e: e[0])
    if not parsed.errors:
        by_module.insert(0, (".msbuild.props", ws.msbuild_props))
        redirects = ws.collect_redirects()
        by_module.insert(1, (".bindingredirects", redirects))

    dumped = dump(dict(by_module), sort_keys=False)
    print(dumped)


if __name__ == "__main__":
    main()
