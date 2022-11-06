import re
import sys
import xml.etree.ElementTree as ET


def dump(fname):
    parsed = ET.parse(fname)

    tags = set(el.tag for el in parsed.iter())
    print("class Tags:")
    for t in sorted(tags):
        name = re.sub("{.*}", "", t).replace(".", "_")
        print(f'    {name} = "{t}"')
    print(tags)


dump(sys.argv[1])
