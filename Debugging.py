from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB


stdin = b""
#with open(r"C:\Users\Matthew\Documents\Games\Visual Boy Advance\roms\Golden Sun - The Lost Age (UE) [!].gba","rb") as f:
#with open(r"C:\Users\Matthew\Documents\Games\mGBA\Golden Sun (UE) [!].gba","rb") as f:
with open(r"C:\Users\Matthew\Documents\Games\Visual Boy Advance\roms\Golden Sun - The Lost Age (UE) [!].gba","rb") as f:
    stdin = f.read()

Thumb = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
Arm = Cs(CS_ARCH_ARM, CS_MODE_ARM)


def disT(addr=0, length=1, disformat="debug", data=stdin):
    instructions = [None]*length
    for i in range(length):
        if type(data) == int:
            numshorts = max(0,int.bit_length(data)-1)//16 + 1 
            data = int.to_bytes(data,numshorts*2,"little")
        if 0xF000 <= int.from_bytes(data[addr:addr+2],"little") < 0xF800 and int.from_bytes(data[addr+2:addr+4],"little") >= 0xF800:
                address,size,mnemonic,op_str = next(Thumb.disasm_lite(data[addr:addr+4],addr))
        elif int.from_bytes(data[addr:addr+2],"little") == 0xF800:
            address,size,mnemonic,op_str = addr,2,"bl",""
        else:
            try: address,size,mnemonic,op_str = next(Thumb.disasm_lite(data[addr:addr+4],addr))
            except StopIteration: address,size,mnemonic,op_str = addr,2,"",""
        code = f"{int.from_bytes(data[addr:addr + size],'little'):04x}"
        instructions[i] = (address,size,mnemonic,op_str,code)
        addr += size
    show(instructions,disformat)


def disA(addr=0, length=1, disformat="debug", data=stdin):
    instructions = [None]*length
    for i in range(length):
        if type(data) == int:
            numints = max(0,int.bit_length(data)-1)//32 + 1
            data = int.to_bytes(data,numints*4,"little")
        try: address,size,mnemonic,op_str = next(Arm.disasm_lite(data[addr:addr+4],addr))
        except StopIteration: address,size,mnemonic,op_str = addr,4,"",""
        code = f"{int.from_bytes(data[addr:addr+size],'little'):08x}"
        instructions[i] = (address,size,mnemonic,op_str,code)
        addr += size
    show(instructions,disformat)


def disFuncT(addr, disformat="debug", data=stdin):
    length = boundsT(addr,data)[3] + 1
    disT(addr,length,disformat,data)


def disFuncA(addr, disformat="debug", data=stdin):
    length = boundsA(addr,data)[3] + 1
    disA(addr,length,disformat,data)


def show(instructions, disformat="debug"):
    fields = ("address","size","mnemonic","op_str","code")
    for f in fields: disformat = disformat.replace(f,str(fields.index(f)))
    disformat = disformat.replace("{command}","{2} {3}")
    if disformat == "debug": disformat = "{0:08x}:  {4:8s}\t{2} {3}"
    
    for i in instructions:
        print(disformat.format(*i))


def boundsT(addr, data=stdin):
    addr -= addr%2
    start,end = addr, addr
    while data[start+1] != 0xB5:
        start -= 2
    while data[end+1] != 0xBD:
        if 0x4700 <= int.from_bytes(data[end:end+2],"little") <= 0x4770: break
        end += 2
    count = (end-start)//2 + 1
    hereToEnd = (end-addr)//2
    for i in range(start,end,2):
        code = int.from_bytes(data[i:i+4],"little")
        low,high = code & 0xFFFF, code >> 16
        if 0xF000 <= low < 0xF800 and high >= 0xF000:
            count -= 1
            if i >= addr: hereToEnd -= 1
    return hex(start),hex(end),count,hereToEnd


def boundsA(addr, data=stdin):
    addr -= addr%4
    start,end = addr, addr
    while data[start:start+2] != int.to_bytes(0x4778,2,"little"):
        start -= 4
    while data[end:end+4] != int.to_bytes(0xE12FFF1E,4,"little"):
        end += 4
    return hex(start),hex(end),(end-start)//4 + 1,(end-addr)//4


def bl_code(start,end):
    diff = (end-start-4)//2 % 2**22
    low,high = diff & 0x7FF, diff >> 11
    print(f"{0xF000 + high:X} {0xF800 + low:X}")


def bl_offset(data):
    if type(data) == list: data = bytes(data)
    if type(data) == bytes: data = int.from_bytes(data,"little")
    return 2*(((data & 0x7FF ^ 0x400) << 11 | (data >> 16) & 0x7FF) - 0x200000 + 2)


masterlist = {}
"""masterlist is a dictionary of functions, each paired with a tuple of two lists: {funcname: ([parent funcs], [child funcs])}
generateFuncList causes masterlist to be updated with any new connections"""


def generateFuncList(addr, display=False, depth=0, src=stdin, des=masterlist):
    
    """Generates a function network starting from addr

    Arguments:
        addr -- the starting point; integer relative to the base address of the rom
        display -- print the progress of the generator as it goes
        depth -- set to a number greater than 0 to limit the search depth
        src -- the raw binary data
        des -- the dictionary in which to store the resultant function network
    """

    s = f"08{hex(addr)[2:]:0>6}"
    path = [s]
    totalFuncList = set()
    currentFuncList = [set()]
    currentBranchList = [set()]
    if s not in des: des[s] = ([],[])

    def navigate_tree(addr):
        nonlocal s
        newentry = ""
        stepinto = True
        endfunc = False

        while True:
            instr = int.from_bytes(src[addr:addr+2],"little")

            # b {conditional}; updates the local list of branches of the function
            if 0xD000 <= instr < 0xDE00:
                offset = 2*((instr&0xFF^0x80)-0x80) + 4
                if offset > 0: currentBranchList[-1].add(addr + offset)

            # b {unconditional}; branches to the smallest address in the local branch list that's greater than addr
            elif 0xE000 <= instr < 0xE800:
                offset = 2*((instr&0x7FF^0x400)-0x400) + 4
                if offset > 0:
                    currentBranchList[-1] = set(filter(lambda x: x > addr, currentBranchList[-1] | {addr + offset}))
                    addr = min(currentBranchList[-1])
                    continue

            # bl instructions
            elif 0xF000 <= instr < 0xF800 and int.from_bytes(src[addr+2:addr+4],"little") >= 0xF800:
                newaddr = addr + bl_offset(src[addr:addr+4])
                newentry = f"08{hex(newaddr)[2:]:0>6}"
                addr += 2

            # bx instructions
            elif 0x4700 <= instr <= 0x4770:
                if instr <= 0x4738 and (instr & 0x38) >> 3 == src[addr-1] & 0x7:
                    newaddr = int.from_bytes(src[addr+2:addr+6],"little")
                    newentry = f"{hex(newaddr-(newaddr&1))[2:]:0>8}"
                    if not (newaddr & 1 and newaddr>>27 & 1): stepinto = False # if it's not thumb, don't step into it
                    newaddr &= 0xFFFFFE
                endfunc = True

            # pop {pc}
            elif instr>>8 == 0xBD: endfunc = True
            
            if newentry and newentry not in currentFuncList[-1]:
                currentFuncList[-1].add(newentry)
                if display:
                    if len(currentFuncList[-1]) > 1:
                        print(s)
                        s = f"{' '*(len(path)*13-3)}|- {newentry}"
                    else: 
                        s += " --- " + newentry
                
                # update masterlist
                if newentry not in des[path[-1]][1]: des[path[-1]][1].append(newentry)
                if newentry not in des: des[newentry] = ([path[-1]],[])
                elif newentry not in des[newentry][0]: des[newentry][0].append(path[-1])

                # step into the new function recursively
                if stepinto and (depth == 0 or depth > len(path)) and newentry not in totalFuncList:
                    totalFuncList.add(newentry)
                    currentFuncList.append(set())
                    currentBranchList.append(set())
                    path.append(newentry)
                    navigate_tree(newaddr)

            # return by exiting navigate_tree
            if endfunc:
                currentFuncList.pop()
                currentBranchList.pop()
                path.pop()
                break
            
            newentry = ""
            addr += 2

    navigate_tree(addr)
    if display: print(s)


def tree(addr, depth=0, showall=True, reverse=False, src=masterlist):

    """Prints a tree to the console
    
    Arguments:
        addr -- the starting point; integer relative to the base address of the rom
        depth -- set to a number greater than 0 to limit the search depth
        showall -- set to False to prevent expansion of functions that have already been expanded
        reverse -- set to True to find the addresses that led to the specified address
        src -- a dictionary where each entry is in the format {funcname : ([parent funcs], [child funcs])}
    """

    s = f"08{hex(addr)[2:]:0>6}"
    if reverse: direction = 0
    else: direction = 1
    iterables = [iter(src[s][direction])]
    funclist = set()
    newline = False

    while iterables:
        try: 
            nextfunc = next(iterables[-1])
            iterables.append(iter(src[nextfunc][direction]))
            if newline: 
                print(s)
                s = f"{' '*(len(iterables)*13-16)}|- {nextfunc}"
                newline = False
            else:
                s += " --- " + nextfunc
            if (not showall and nextfunc in funclist) or (0 != depth < len(iterables)): 
                raise StopIteration
            else: 
                funclist.add(nextfunc)

        except StopIteration:
            iterables.pop()
            newline = True
            
    print(s)

































# def tree(dictionary, display="default"):
#     history = []
#     iterables = []
#     s = ""

#     if display in ("default",0): 
#         display = lambda spaces,key: ("\n" + " "*spaces + "|")*2 + f"- {key} --- "
#     elif display in ("compact",1):
#         display = lambda spaces,key: f'\n{"-":>{spaces+2}} {key} --- '

#     while True:
#         while True:
#             iterables.append(iter(dictionary))
#             try: key = next(iterables[-1])
#             except StopIteration: break
#             history.append(dictionary)
#             s += key + " --- "
#             dictionary = dictionary[key]
   
#         while True:
#             try: dictionary = history.pop()
#             except IndexError: return s[:-5]
#             iterables.pop()
#             try: key = next(iterables[-1])
#             except StopIteration: continue
#             else:
#                 history.append(dictionary)
#                 dictionary = dictionary[key]
#                 s = s[:-5] + display(len(history)*13-16,key)
#                 break

