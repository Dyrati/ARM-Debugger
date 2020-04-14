import re


def extract(instr, matchi=re.compile(r"\s*([a-zA-Z]+)\s*(.*?(?=\(|//|$))"), matchb=re.compile(r"\[?{?(\w*)\]?}?"), 
            replacements={" ":"", "sp":"r13", "lr":"r14", "pc":"r15", "$":"0x", "#":""}):

    """Extracts and returns the arguments and argument types of the user input"""

    name, instr = matchi.match(instr).groups()
    args = [(name, str)]  # output
    groups = []  # used to contain things within brackets
    reglist = 0
    des = args

    for k,v in replacements.items(): instr = instr.replace(k,v)
    instr = re.sub(r"\bx", "0x", instr)
    clist = instr.split(",")
    if not clist[0]: clist = []

    for string in clist: 
        value = matchb.sub(r"\1",string)
        if string[0] == "[": des = groups
        elif string[0] == "{": des = reglist
        if type(des) is int:
            if value:
                value = value.replace("r","").split("-")
                if len(value) == 1: reglist |= 2**int(value[0])
                else: reglist |= 2**(int(value[1])+1)-2**int(value[0])
        elif value[0] == "r": 
            des.append((int(value.replace("!","")[1:]),str))
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


def setbits(bitmask, value):
    value <<= max(0,int.bit_length(bitmask & -bitmask) - 1)
    if max(value,-value) > bitmask: raise ValueError("Value out of range")
    return value & bitmask


def thumb_shift(args):
    out = setbits(3<<11, ("lsl", "lsr", "asr").index(args[0]))
    offset = 1 if len(args) < 4 else 0
    out |= setbits(31<<6, args[3-offset]) | setbits(7<<3, args[2-offset]) | setbits(7, args[1])
    return out


def thumb_add(args, types):
    if args[1] == 13 and types[1] is str:
        out = 0xb000
        if args[2] < 0: out |= setbits(0xff, 0x80-args[2]//4)
        else: out |= setbits(0x7f, args[2]//4)
    elif args[2] in {13,15} and types[2] is str:
        out = 0xa000
        if args[2] == 13: out |= 1<<11
        out |= setbits(7<<8, args[1]) | setbits(0xff, args[3]//4)
    elif types[2] is int:
        out = 0x3000 | setbits(7<<8, args[1]) | setbits(0xff, args[2])
    else:
        out = 0x1800
        if len(args) < 4:
            out |= setbits(7<<6, args[2]) | setbits(7<<3, args[1]) | setbits(7, args[1])
        else:
            if types[3] is int: out |= 1<<10
            out |= setbits(7<<6, args[3]) | setbits(7<<3, args[2]) | setbits(7, args[1])
    return out


def thumb_sub(args, types):
    if args[1] == 13 and types[1] is str:
        out = 0xb080 | setbits(0x7f, args[2]//4)
    elif types[2] is int:
        out = 0x3800 | setbits(7<<8, args[1]) | setbits(0xff, args[2])
    else:
        out = 0x1a00
        offset = 1 if len(args) < 4 else 0
        if not offset and types[3] is int: out |= 1<<10
        out |= setbits(7<<6, args[3-offset]) | setbits(7<<3, args[2-offset]) | setbits(7, args[1])
    return out


def thumb_mov(args, types):
    if types == (str,str,str):
        out = 0x1c00 | setbits(7<<3, args[2]) | setbits(7, args[1])
    else:
        out = 0x2000 | setbits(7<<8, args[1]) | setbits(0xff, args[2])
    return out


def thumb_cmp(args):
    return 0x2800 | setbits(7<<8, args[1]) | setbits(0xff, args[2])


def thumb_alu(args):
    out = 0x4000 | setbits(7, args[1]) | setbits(7<<3, args[2])
    alu_op = ("and","eor","lsl","lsr","asr","adc","sbc","ror","tst","neg","cmp","cmn","orr","mul","bic","mvn").index(args[0])
    out |= setbits(15<<6, alu_op)
    return out


def thumb_HiReg(args):
    out = 0x4400
    out |= setbits(3<<8, ("add", "cmp", "mov").index(args[0]))
    if args[1] >= 8: out |= 1<<7
    if args[2] >= 8: out |= 1<<6
    out |= setbits(7<<3, args[2] % 8)
    out |= setbits(7, args[1] % 8)
    return out


def thumb_nop(args): 
    return 0x46c0

def thumb_bx(args):
    return 0x4700 | setbits(15<<3, args[1])

def thumb_blx(args):
    return 0x4780 | setbits(15<<3, args[1])


def thumb_str(args, types):
    if args[2][0] == 13:
        out = 0x9000 | setbits(7<<8, args[1]) | setbits(0xff, args[2][1]//4)
    else:
        out = setbits(7, args[1]) | setbits(7<<3, args[2][0])
        if types[2][1] is int:
            out |= 0x6000 | setbits(31<<6, args[2][1]//4)
        else:
            out |= 0x5000 | setbits(7<<6, args[2][1])
    return out


def thumb_strb(args, types):
    out = setbits(7, args[1]) | setbits(7<<3, args[2][0])
    if types[2][1] is int:
        out |= 0x7000 | setbits(31<<6, args[2][1])
    else:
        out |= 0x5400 | setbits(7<<6, args[2][1])
    return out


def thumb_strh(args, types):
    out = setbits(7, args[1]) | setbits(7<<3, args[2][0])
    if types[2][1] is int:
        out |= 0x8000 | setbits(31<<6, args[2][1]//2)
    else:
        out |= 0x5200 | setbits(7<<6, args[2][1])
    return out


def thumb_ldr(args, types, pc):
    if types[2][0] is int:
        out = 0x4800 | setbits(7<<8, args[1]) | setbits(0xff, (args[2][0] - (pc & ~2))//4)
    elif args[2][0] == 15:
        out = 0x4800 | setbits(7<<8, args[1]) | setbits(0xff, args[2][1]//4)
    elif args[2][0]==13:
        out = 0x9800 | setbits(7<<8, args[1]) | setbits(0xff, args[2][1]//4)
    else:
        out = setbits(7, args[1]) | setbits(7<<3, args[2][0])
        if types[2][1] is int:
            out |= 0x6800 | setbits(31<<6, args[2][1]//4)
        else:
            out |= 0x5800 | setbits(7<<6, args[2][1])
    return out


def thumb_ldrb(args, types):
    out = setbits(7, args[1]) | setbits(7<<3, args[2][0])
    if types[2][1] is int:
        out |= 0x7800 | setbits(31<<6, args[2][1])
    else:
        out |= 0x5c00 | setbits(7<<6, args[2][1])
    return out


def thumb_ldsb(args):
    return 0x5600 | setbits(7, args[1]) | setbits(7<<3, args[2][0]) | setbits(7<<6, args[2][1])


def thumb_ldrh(args, types):
    out = setbits(7, args[1]) | setbits(7<<3, args[2][0])
    if types[2][1] is int:
        out |= 0x8800 | setbits(31<<6, args[2][1]//2)
    else:
        out |= 0x5a00 | setbits(7<<6, args[2][1])
    return out


def thumb_ldsh(args):
    return 0x5e00 | setbits(7, args[1]) | setbits(7<<3, args[2][0]) | setbits(7<<6, args[2][1])


def thumb_push(args):
    out = 0xb400 | setbits(0xff, args[1] & 0xbfff)
    if args[1] & 1<<14: out |= 1<<8
    return out


def thumb_pop(args):
    out = 0xbc00 | setbits(0xff, args[1] & 0x7fff)
    if args[1] & 1<<15: out |= 1<<8
    return out


def thumb_stm(args):
    return 0xc000 | setbits(7<<8, args[1]) | setbits(0xff, args[2])

def thumb_stmia(args):
    return 0xc000 | setbits(7<<8, args[1]) | setbits(0xff, args[2])

def thumb_ldm(args):
    return 0xc800 | setbits(7<<8, args[1]) | setbits(0xff, args[2])

def thumb_ldmia(args):
    return 0xc800 | setbits(7<<8, args[1]) | setbits(0xff, args[2])

def thumb_swi(args):
    return 0xdf00 | setbits(0xff, args[1])

def thumb_svc(args):
    return 0xdf00 | setbits(0xff, args[1])

def thumb_bkpt(args):
    return 0xbe00 | setbits(0xff, args[1])


def thumb_b_if(args, types, pc):
    out = 0xd000
    bType = ("beq","bne","bcs","bcc","bmi","bpl","bvs","bvc","bhi","bls","bge","blt","bgt","ble").index(args[0])
    out |= setbits(15<<8, bType) | setbits(0xff, (args[1]-pc)//2)
    return out

def thumb_b(args, pc):
    return 0xe000 | setbits(0x7ff, (args[1]-pc)//2)

def thumb_bl(args, pc):
    if len(args) == 1: 
        out = 0xf800
    else:
        out = 0xf800f000
        out |= setbits(0x7ff0000, (args[1]-pc)//2 & 0x7ff)
        out |= setbits(0x7ff, (args[1]-pc)//2 >> 11)
    return out

def thumb_blh(args):
    return 0xf800 | setbits(0x7ff, args[1]//2)


ConditionalBranches = {"beq","bne","bcs","bcc","bmi","bpl","bvs","bvc","bhi","bls","bge","blt","bgt","ble"}
AluOps = {"and","eor","lsl","lsr","asr","adc","sbc","ror","tst","neg","cmp","cmn","orr","mul","bic","mvn"}
MultiTypes = {"add","sub","mov","str","strb","strh","ldr","ldrb","ldrh"}
PC_Relative = {"ldr", "b", "bl"}
BarrelShift = {"lsl", "lsr", "asr"}


def assemble(instr, pc=None):

    """Converts assembly code into machine code"""

    global ConditionalBranches, AluOps, MultiTypes, PC_Relative, BarrelShift
    if pc == None: pc = 4
    args, types = extract(instr)
    name = args[0]

    if types == (str, str, str):
        if args[1] > 7 or args[2] > 7: return thumb_HiReg(args)
        elif name in AluOps: return thumb_alu(args)
    if ("thumb_" + name) in globals():
        inputs = [args]
        if name in MultiTypes: inputs.append(types)
        if name in PC_Relative: inputs.append(pc)
        return globals()["thumb_" + name](*inputs)
    elif name in BarrelShift: return thumb_shift(args)
    elif name in ConditionalBranches: return thumb_b_if(args, types, pc)
    else: raise KeyError(f"'{name}' not recognized")
