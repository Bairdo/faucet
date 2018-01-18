import argparse
import collections
import os
import re


# TODO allow set_defualts()
# TODO Override default by a comment after the default.
#  e.g. 'interfaces': {}. # configuration block ...


def get_block(pattern, text):
    m = re.search(pattern, text)
    pos = m.end() - 2
    openBr = 0
    while True:
        pos += 1
        if text[pos] == '{':
            openBr += 1
        elif text[pos] == '}':
            openBr -= 1
        if openBr == 0:
            break
    return text[m.start(): pos+1]

def dict_to_csv(hdr, d, filename):
    with open('%s.csv' % filename, 'w') as csv:
        hdr_str = ""
        for col in hdr:
            hdr_str += (col)
            hdr_str += ('#')
        hdr_str = hdr_str[:-1]
        csv.write(hdr_str)

        for k, v in d.items():
            s = "\n{}#{}#{}#{}".format(k, v[0], v[1], v[2])
            csv.write(s)
 
        print("done %s" % filename)

def main(input_files):

    for path in input_files:
        with open(path, 'r') as f:
            s = f.read()
        defaults_text = get_block('defaults = {', s)

        defaults = collections.OrderedDict()
        previous = ""
        for line in defaults_text.split('\n'):
            try:
                l = line.strip()
                if l[0] == '#':
                    defaults[previous][2] += l.strip('#').strip()
                    continue
                var, val = l.split("': ")
                previous = var.strip("'")
                defaults[previous] = ['', '', ''] # val, type, comment
                defaults[previous][0] = val.strip().strip(',')
            except ValueError as e:
                print(l, e)
                pass

        defaults_types_text = get_block('defaults_types = {', s)
        for line in defaults_types_text.split('\n'):
            try:
                l = line.strip()

                if l[0] == '#':
                    continue
                var, val = l.split("': ")
                defaults[var.strip("'")][1] = val.strip().strip(',')
            except ValueError as e:
                print(l, e)
                pass

        basename = os.path.basename(path)       
        dict_to_csv(['Attribute', 'Default', 'Type', 'Description'], defaults, basename)
        

if __name__ == '__main__':
    parser = argparse.ArgumentParser('Extract documentation table from python file.')
    parser.add_argument('-i', '--input', type=str, nargs='+', help='input file')

    args = parser.parse_args()

    main(args.input)
