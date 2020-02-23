import re


commands = {
    "initial":[("A[0][0] == 'b' and A[0] not in {'b','bx','bl','blx','blh','bkpt'}","b_if"), 
        ("A[0] in {'add','sub'}",""), ("len(A) == 3 and T[1:] == (str,str)",3), 
        ("A[0] in {'lsl','lsr','asr'}","shift"), "", ("A[1]>7 or A[2]>7","HiReg"), ("A[0] == 'mov'","add"), "alu"],
    "shift":[(3<<11,("lsl","lsr","asr")), (31<<6,"A[3-int(len(A)<4)]"), (7<<3,"A[2-int(len(A)<4)]"), (7,"A[1]")],
    "add":[("A[1]==13",23), ("A[2] in {13,15}",28), ("T[2] is int",17),
        (0xFFFF,0x1800), ("len(A)<4",6), (1<<10,"T[3] is int"), (7<<6,"A[3]"), (7<<3,"A[2]"), (7,"A[1]"), -1,
            ("A[0]=='mov'",5), (7<<6,"A[2]"), (7<<3,"A[1]"), (7,"A[1]"), -1,
            (1<<10, 1), (7<<3,"A[2]"), (7,"A[1]"), -1,
        (0xFFFF,0x3000), (7<<8,"A[1]"), (0xFF,"A[2]"), -1,
        (0xFFFF,0xb000), ("A[2]<0",3), (0x7F,"A[2]//4"), -1, (0xFF,"0x80-A[2]//4"), -1, 
        (0xFFFF,0xA000), (1<<11,"A[2]==13"), (7<<8,"A[1]"), (0xFF,"A[3]//4")],
    "sub":[("A[1]==13",17), ("T[2] is int",12),
        (0xFFFF,0x1A00), ("len(A)<4",6), (1<<10,"T[3] is int"), (7<<6,"A[3]"), (7<<3,"A[2]"), (7,"A[1]"), -1,
            (7<<6,"A[2]"), (7<<3,"A[1]"), (7,"A[1]"), -1,
        (0xFFFF,0x3800), (7<<8,"A[1]"), (0xFF,"A[2]"), -1,
        (0xFFFF,0xb080), (0x7F,"A[2]//4")],
    "mov":[(0xFFFF,0x2000), (7<<8,"A[1]"), (0xFF,"A[2]")],
    "cmp":[(0xFFFF,0x2800), (7<<8,"A[1]"), (0xFF,"A[2]")],
    "alu":[(0xFFFF,0x4000), (7,"A[1]"), (7<<3,"A[2]"),
        (15<<6,("and","eor","lsl","lsr","asr","adc","sbc","ror","tst","neg","cmp","cmn","orr","mul","bic","mvn"))],
    "HiReg":[(0xFFFF,0x4400), (3<<8,("add","cmp","mov")), (1<<7,"A[1]>=8"), (15<<3,"A[2]"), (7,"A[1]%8")],
    "nop":[(0xFFFF,0x46c0)],
    "bx":[(0xFFFF,0x4700), (15<<3,"A[1]")],
    "blx":[(0xFFFF,0x4780), (15<<3,"A[1]")],
    "str":[("A[2][0]==13",10), (7,"A[1]"), (7<<3,"A[2][0]"), ("T[2][1] is int",4),
        (0xF000, 5), (7<<6,"A[2][1]"), -1,
        (0xF000, 6), (31<<6,"A[2][1]//4"), -1,
        (0xF000, 9), (7<<8,"A[1]"), (0xFF,"A[2][1]//4")],
    "strb":[(7,"A[1]"), (7<<3,"A[2][0]"), ("T[2][1] is int",4),
        (0xFF00,0x54), (7<<6,"A[2][1]"), -1,
        (0xFF00,0x70), (31<<6,"A[2][1]")],
    "strh":[(7,"A[1]"), (7<<3,"A[2][0]"), ("T[2][1] is int",4),
        (0xFF00,0x52), (7<<6,"A[2][1]"), -1,
        (0xFF00,0x80), (31<<6,"A[2][1]//2")],
    "ldr":[("A[2][0]==15",15), ("A[2][0]==13",10), (7,"A[1]"), (7<<3,"A[2][0]"), ("T[2][1] is int",4),
        (0xFF00,0x58), (7<<6,"A[2][1]"), -1,
        (0xFF00,0x68), (31<<6,"A[2][1]//4"), -1,
        (0xFF00,0x98), (7<<8,"A[1]"), (0xFF,"A[2][1]//4"), -1,
        (0xFF00,0x48), (7<<8,"A[1]"), (0xFF,"A[2][1]//4")],
    "ldrb":[(7,"A[1]"), (7<<3,"A[2][0]"), ("T[2][1] is int",4),
        (0xFF00,0x5c), (7<<6,"A[2][1]"), -1,
        (0xFF00,0x78), (31<<6,"A[2][1]")],
    "ldsb":[(0xFF00,0x56), (7,"A[1]"), (7<<3,"A[2][0]"), (7<<6,"A[2][1]")],
    "ldrh":[(7,"A[1]"), (7<<3,"A[2][0]"), ("T[2][1] is int",4),
        (0xFF00,0x5a), (7<<6,"A[2][1]"), -1,
        (0xFF00,0x88), (31<<6,"A[2][1]//2")],
    "ldsh":[(0xFF00,0x5e), (7,"A[1]"), (7<<3,"A[2][0]"), (7<<6,"A[2][1]")],
    "push":[(0xFF00,0xb4), (0xFF,"A[1] & 0xFF"), (1<<8,"A[1]>>14")],
    "pop":[(0xFF00,0xbc), (0xFF,"A[1] & 0xFF"), (1<<8,"A[1]>>15")],
    "stm":[(0xFF00,0xc0), (7<<8,"A[1]"), (0xFF,"A[2]")], "stmia":["stm"],
    "ldm":[(0xFF00,0xc8), (7<<8,"A[1]"), (0xFF,"A[2]")], "ldmia":["ldm"],
    "swi":[(0xFF00,0xdf), (0xFF,"A[1]")], "svc":["swi"],
    "bkpt":[(0xFF00,0xbe), (0xFF,"A[1]")],
    "b_if":[(0xFF00,0xd0), (15<<8,("beq","bne","bcs","bcc","bmi","bpl","bvs","bvc","bhi","bls","bge","blt","bgt","ble")),
        (0xFF,"(A[1]-pc)//2")],
    "b":[(0xFF00,0xe0), (0x7ff,"(A[1]-pc)//2")],
    "bl":[("len(A)>1",3), (0xFF,0xF8), -1, (0xF800F000,0xF800F), 
        (0x7FF<<16,"(A[1]-pc)//2"), (0x7FF,"((A[1]-pc)//2)>>11")],
    "blh":[(0xFF,0xF8), (0x7FF,"A[1]//2")],
}


def extract(instr):    
    args = []
    groups = []
    reglist = 0
    des = args

    replacements = {"sp":"r13", "lr":"r14", "pc":"r15", "\$":"0x", "#":"", r"\bx":"0x"}
    for k,v in replacements.items(): instr = re.sub(k,v,instr)
    separator = re.compile("[^, ]+")
    brackets = re.compile("\[?{?(\w*)\]?}?")
    clist = separator.findall(instr)
    args.append((clist[0],str))

    for string in clist[1:]: 
        value = brackets.sub(r"\1",string)
        if string[0] == "[": des = groups
        elif string[0] == "{": des = reglist
        if type(des) is int:
            if value:
                value = value.replace("r","").split("-")
                if len(value) == 1: reglist |= 2**int(value[0])
                else: reglist |= 2**(int(value[1])+1)-2**int(value[0])
        elif value[0] == "r": des.append((int(value.replace("!","")[1:]),str))
        else: 
            try: des.append((int(value),int))
            except ValueError: des.append((int(value,16),int))
        if string[-1] == "]": 
            des = args
            if len(groups) == 1: groups.append((0,int))
            args.append(zip(*groups))
            groups.clear()
        elif string[-1] == "}":
            des = args
            args.append((reglist,int))
            reglist = 0
    return zip(*args)


def assemble(instr, pc=4):
    out = 0
    index = 0
    A,T = extract(instr)
    template = commands["initial"]

    def setval(bitmask,value):
        nonlocal out
        value <<= max(0,int.bit_length(bitmask & -bitmask) - 1)
        if max(value,-value) > bitmask: raise ValueError
        out = out & ~bitmask | value & bitmask

    def changeindex(value):
        nonlocal index,template
        if value == -1: index = len(template)
        elif type(value) is int: index += value-1
        else:
            index = -1
            try: template = commands[value]
            except KeyError: template = commands[A[0]]

    # Calculate
    while index < len(template):
        code = template[index]
        if type(code) in {int,str}: changeindex(code)
        else:
            c1,c2 = code
            t1,t2 = type(c1),type(c2)
            if t1 is str:
                if eval(c1): changeindex(c2)
            elif t2 is int: setval(c1,c2)
            elif t2 is str: setval(c1,int(eval(c2)))
            elif t2 is tuple: setval(c1,c2.index(A[0]))
        index += 1
    return out

