import re
from typing import Dict


def expand_variables(text: str, vars: Dict[str, str]):

    def replacer(mo):
        got = vars.get(mo.group(1).lower())
        if not got:
            ...
            #print("Variable not found",mo)
        return got or mo.group(0)

    if "$(" not in text:
        return text

    newtext = re.sub(r"\$\((\S+?)\)", replacer, text)
    return newtext


def expand_recursive(vars: Dict[str, str]):
    """ expand many times until no changes, mutates args """

    tries = 0
    while 1:
        dirty = False
        for k,v in vars.items():
            if "$(" not in v:
                continue
            vars[k] = expand_variables(vars[k], vars)
            dirty = True

        if not dirty:
            return
        tries += 1
        if tries > 10:
            raise Exception(f"Can't expand variables {vars}")

