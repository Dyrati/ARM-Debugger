import re
from bisect import bisect_right


BIOS, RAM, ROM = bytearray(), bytearray(), bytearray()
RegionMarkers = {}
suffixes = ["eq","ne","cs","cc","mi","pl","vs","vc","hi","ls","ge","lt","gt","le","","nv"]


def mem_read(addr,size=4):
    region = addr >> 24 & 0xF
    if region in RegionMarkers:
        base, length = RegionMarkers[region]
        reladdr = (addr & 0xFFFFFF) % length + base
        return int.from_bytes(RAM[reladdr:reladdr + size],"little")
    else:
        if region >= 8:
            reladdr = addr - 0x08000000
            return int.from_bytes(ROM[reladdr:reladdr+size],"little")  
        elif region == 0:
            reladdr = addr % 0x4000
            return int.from_bytes(BIOS[reladdr:reladdr+size],"little")
        else: return 0


ThumbBounds = (
    0x1800,0x2000,0x4000,0x4400,0x4800,0x5000,0x6000,0x9000,0xA000,0xB000,0xB100,
    0xB400,0xBE00,0xC000,0xD000,0xDE00,0xDF00,0xE000,0xE800,0xF000,0xF800,0x10000,0xF800F000
)

ArmTree = {
    0:(27,36), 1:(26,31), 2:(25,28), 3:(4,9), 4:([25<<20,16<<20],6), 5:0, 6:(7,8), 7:1,
    8:5, 9:(7,19), 10:([25<<20,16<<20],12), 11:0, 12:(6,16), 13:(22,15), 14:2, 15:3, 
    16:(5,18), 17:4, 18:16, 19:([3<<5,0],23), 20:(22,22), 21:7, 22:7, 23:(24,27),
    24:(23,26), 25:5, 26:5, 27:6, 28:([25<<20,16<<20],30), 29:0, 30:1, 31:(25,33), 
    32:8, 33:(4,35), 34:8, 35:9, 36:(26,40), 37:(25,39), 38:10, 39:11,
    40:(25,44), 41:([15<<21,2<<21],43), 42:13, 43: 15, 44:(24,48), 45:(4,47), 46:12, 47:14,
    48:16
}


def getFuncIndex(instr,Mode):
    if Mode: 
        return bisect_right(ThumbBounds,instr)
    else:
        treepos = 0
        while True:
            try: 
                condition = ArmTree[treepos][0]
                if type(condition) is int:
                    if instr>>condition & 1: treepos = ArmTree[treepos][1]
                    else: treepos += 1
                else:
                    bitmask,value = condition
                    if instr & bitmask == value: treepos = ArmTree[treepos][1]
                    else: treepos += 1
            except TypeError:
                return ArmTree[treepos]


def rlist(number):
    out = []
    state = 0
    for i in range(16):
        if number & 2**i:
            sep = ", "
            if state > 1: out.pop(); sep = "-"
            out.append(f"{sep}r{i}")
            state += 1
        else: state = 0
    return "".join(out)[2:]


ThumbDisasmTree = {
    0:[(("lsl","lsr","asr","ror"),3<<11), (" r{0}, r{1}, 0x{2:x}", 7, 7<<3, 31<<6)],
    1:[(("add","sub"),1<<9), (" r{0}, r{1}, ", 7, 7<<3), (("r","0x"),1<<10), ("{0:x}", 7<<6)],
    2:[(("mov","cmp","add","sub"),3<<11), (" r{0}, 0x{1:x}", 7<<8, 255)],
    3:[(("and","eor","lsl","lsr","asr","adc","sbc","ror","tst","neg","cmp","cmn","orr","mul","bic","mvn"),15<<6), 
        (" r{0}, r{1}", 7, 7<<3)],
    4:[([3<<8,3],8), ([3<<6,0],-1), ([0xFF,0xC0],9), (("add","cmp","mov"),3<<8), " r", ["8*{1}+{0}", 7, 1<<7], ",", 2, 
        (("bx","blx"),1<<7), (" r{0}",15<<3), -1, "nop"],
    5:[("ldr r{0}, [r15, 0x",7<<8), ["4*{0}",255,"x"], "]"],
    6:[(9,4), (("str","ldr"),1<<11), (("","b"),1<<10), 2, (("strh","ldsb","ldrh","ldsh"),3<<10), 
        (" r{0}, [r{1}, r{2}]", 7, 7<<3, 7<<6)],
    7:[(13,3), (("strh","ldrh"),1<<11), 3, (("str","ldr"),1<<11), (("","b"),1<<12), (" r{0}, [r{1}, 0x", 7, 7<<3),
        ["({0}^2 if {0} != 2 else 4)*{1}", 3<<12, 31<<6, "x"], "]"],
    8:[(("str","ldr"),1<<11), (" r{0}, [sp, 0x",7<<8), ["4*{0}",255,"x"], "]"],
    9:[("add r{0}, ",7<<8), (("pc","sp"),1<<11), ", 0x", ["4*{0}",255,"x"]],
    10:[(("add","sub"),1<<7), " sp, 0x", ["4*{0}",127,"x"]],
    11:[],
    12:[([3<<9,0,1,3],-1), (("push","pop"),1<<11), " {", ["rlist({0}|{1}<<{2}+14)", 255, 1<<8, 1<<11], "}"],
    13:[(8,2), ("bkpt ${0:x}",255)],
    14:[(("stmia","ldmia"),1<<11), (" r{0}!, ",7<<8), "{", ["rlist({0})",255], "}"],
    15:["b", ["suffixes[{0}]",15<<8], " $", ["(pc if pc is not None else 4) + 2*(({0}^2**7)-2**7)",255,"addr"]],
    16:[],
    17:[("swi ${0:x}",255)],
    18:["b $",["(pc if pc is not None else 4) + 2*(({0}^2**10) - 2**10)",0x7FF,"addr"]],
    19:[],
    20:[],
    21:["bl", ([0x7FF,0],-1), "h $", ["2*{0}",0x7FF,"X"]],
    22:[],
    23:["bl $", ["(pc if pc is not None else 4) + ((({0}^0x400) << 11 | {1}) - 0x200000)*2", 0x7FF, 0x7FF<<16, "addr"]],
}

ArmDisasmTree = {
    0:[(("and","eor","sub","rsb","add","adc","sbc","rsc","tst","teq","cmp","cmn","orr","mov","bic","mvn"),15<<21), 
        ["c"], ([15<<21,8,9,10,11],3), (("","s"),1<<20), (" r{0},",15<<12), ([15<<21,13,15],2), (" r{0},",15<<16), (25,15), 
        (" r{0}",15), ([255<<4,0],-1), ", ", ([255<<4,6],3), (("lsl","lsr","asr","ror"),3<<5), 3, "rrx", -1, (4,4), " #", 
        ["{0} or 32",31<<7], -1, (" r{0}", 15<<8), -1, " 0x", ["({0}<<32 | {0})>>2*{1} & 2**32-1", 0xFF, 15<<8, "x"]],
    1:[(("mrs","msr"),1<<21), ["c"], (21,2), 14, ((" c"," s"),1<<22), "psr_", (("","f"),1<<19), (("","s"),1<<18), 
        (("","x"),1<<17), (("","c"),1<<16), ", ", (25,3), ("r{0}",15), -1, "0x", 
        ["({0}<<32 | {0})>>2*{1} & 2**32-1", 0xFF, 15<<8, "x"], -1, (" r{0}, ", 15<<12), (("cpsr","spsr"),1<<22)],
    2:[(("bx","blx"),1<<5), ["c"], (" r{0}",15)],
    3:["clz", ["c"], (" r{0}, r{1}",15<<12,15)],
    4:[(("qadd","qsub","qdadd","qdsub"),3<<21), ["c"], (" r{0}, r{1}, r{2}", 15<<12,15,15<<16)],
    5:[(24,7), (("mul","mla","","","umull","umlal","smull","smlal"),7<<21), ["c"], (("","s"),1<<20), (23,13), (21,18), 15,
        ([3<<21,1],2), 3, (("smlaw","smulw"),1<<5), 3, (("smla","","smlal","smul"),3<<21), (("b","t"),1<<5), (("b","t"),1<<6), 
        ["c"], ([3<<21,2],2), 3, (" r{0}, r{1}, r{2}, r{3}", 15<<12, 15<<16, 15, 15<<8), -1, ([1<<22 | 1<<5,0], 4), 
        ([3<<21,0], 3), (" r{0}, r{1}, r{2}", 15<<16, 15, 15<<8), -1, (" r{0}, r{1}, r{2}, r{3}", 15<<16, 15, 15<<8, 15<<12)],
    6:["swp", (("","b"),1<<22), ["c"], (" r{0}, r{1}, [r{2}]", 15<<12, 15, 15<<16)],
    7:[([1<<20 | 1<<5,1],3), "ldr", 2, "str", (20,3), (("h","d"),1<<6), 2, (("","h","sb","sh"),3<<5), ["c"], 
        (" r{0},",15<<12), ([1<<20 | 1<<6,1],2), 4, " r", ["{0}+1",15<<12], ",", (" [r{0}",15<<16), (("], ",", "),1<<24), 
        (("-",""),1<<23), (22,3), ("r{0}",15), 3, "0x", ["{0}<<4 | {1}",15<<8,15,"x"], (24,2), -1, "]", (("","!"),1<<21)],
    8:[(("str","ldr"),1<<20), (("","b"),1<<22), (24,2), (("","t"),1<<21), ["c"], (" r{0}, [r{1}",15<<12, 15<<16), 
        (("], ",", "),1<<24), (("-",""),1<<23), (25,3), ("0x{0:x}",0xFFF), 11, ("r{0}",15), ([127<<5,0],9), ", ", 
        ([127<<5,3],2), 3, "rrx", 4, (("lsl","lsr","asr","ror"),3<<5), " #", ["{0} or 32", 31<<7], (24,2), -1, "]", 
        (("","!"),1<<21)],
    9:[],
    10:[(("stm","ldm"),1<<20), (("da","ia","db","ib"),3<<23), ["c"], (" r{0}",15<<16), (("","!"),1<<21), ", {", 
        ["rlist({0})",0xFFFF], "}", (("","^"),1<<22)],
    11:[(("b","bl"),1<<24), ["c"], " $", ["(pc if pc is not None else 8) + (({0}^2**23)-2**23)*4",0xFFFFFF,"addr"]],
    12:["cdp", ["'2' if c == 'nv' else c"], (" p{0}, #{1}, c{2}, c{3}, c{4}, #{5}", 15<<8, 15<<20, 15<<12, 15<<16, 15, 7<<5)],
    13:[(("stc","ldc"),1<<20), ["'2' if c == 'nv' else ''"], (("","l"),1<<22), ["c if c != 'nv' else ''"], 
        (" p{0}, c{1}, [r{2}", 15<<8, 15<<12, 15<<16), (24,2), "]", ", ", (("-",""),1<<23), "0x", ["4*{0}",255,"x"], 
        (24,2), -1, "]", (("","!"),1<<21)],
    14:[(("mcr","mrc"),1<<20), ["'2' if c == 'nv' else c"],
        (" p{0}, #{1}, r{2}, c{3}, c{4}, #{5}", 15<<8, 7<<21, 15<<12, 15<<16, 15, 7<<5)],
    15:[(("mcrr","mrrc"),1<<20), ["'2' if c == 'nv' else c"],
        (" p{0}, #{1}, r{2}, r{3}, c{4}", 15<<8, 15<<4, 15<<12, 15<<16, 15)],
    16:[(27,4), "bkpt $", ["{0}<<4 | {1}", 0xFFF<<8, 15,"X"], -1, "swi", ["c"], (" ${0:x}",2**24-1)],
}



def disasm(instr, Mode=1, pc=None):
    FuncID = getFuncIndex(instr,Mode)
    if Mode: 
        template = ThumbDisasmTree[FuncID]
    else:
        template = ArmDisasmTree[FuncID]
        c = suffixes[instr>>28]

    def getsegment(bitmask):  # returns a segment of instr
        return (instr & bitmask) >> (int.bit_length(bitmask & -bitmask) - 1)

    out = ""
    index = 0
    while index < len(template):
        code = template[index]
        init = index
        T = type(code) 
        if T is tuple:
            arg1,*arg2 = code
            T2 = type(arg1)
            if T2 is tuple: out += arg1[getsegment(arg2[0])]  # [(strings), bitmask] selects a string based on bitmask
            elif T2 is str: out += arg1.format(*map(lambda x:getsegment(x),arg2))  # [str, bitmasks] inserts bitmasks into str
            elif T2 is int:
                if getsegment(1<<arg1): index += arg2[0]  # if correct bit is on, jump
            elif T2 is list:  # [bitmask, values] if bitmask is in values, jump
                if getsegment(arg1[0]) in arg1[1:]: index += arg2[0]
        elif T is str: out += code  # adds str to output
        elif T is int: index += code  # jumps ahead
        elif T is list:  # [str, bitmasks, format] inserts bitmasks into str, then evaluates, and formats
            arg1,*arg2 = code
            if arg2:
                fstr = arg2.pop() if type(arg2[-1]) is str else ""
                if fstr == "addr":  # presets for address strings
                    fstr = "0>8X" if pc else "X"
                newstr = eval(arg1.format(*map(lambda x:getsegment(x),arg2)))
                out += f"{newstr:{fstr}}"
            else: out += eval(arg1)
        if index == init: index += 1
        elif index < init: break

    if pc:  # replaces relative addresses with true addresses (and values in case of ldr)
        def subs(matchobj): 
            addr = (pc&~2) + int(matchobj.group(1), 16)
            return f"[${addr:0>8X}] (=${mem_read(addr,4):0>8X})"
        out = re.sub(r"\[r15, \$?([0-9a-fx]+)\]", subs, out)

    return out.replace("r13","sp").replace("r14","lr").replace("r15","pc").replace("$-","-$") or "[???]"
