
RAM = bytearray()
ROM = bytearray()
RegionMarkers = {}


def bl_offset(data):
    return 2*(((data & 0x7FF ^ 0x400) << 11 | (data >> 16) & 0x7FF) - 0x200000 + 2)


def minmax(bounds, entry):
    if len(bounds) == 2:
        if entry < bounds[0]: bounds[0] = entry
        elif entry > bounds[1]: bounds[1] = entry
    else: bounds.append(entry); bounds.sort()


def mem_read(addr,size=2):
    region = addr >> 24 & 0xF
    if region in RegionMarkers:
        base, length = RegionMarkers[region]
        reladdr = (addr & 0xFFFFFF) % length + base
        value = int.from_bytes(RAM[reladdr:reladdr + size],"little")
    else:
        reladdr = addr - 0x08000000
        value = int.from_bytes(ROM[reladdr:reladdr+size],"little")
    return value


def generateFuncList(addr, depth=0):
    
    """
    Arguments:
        addr    -- the starting point; integer relative to the base address of the rom
        depth   -- set to a number > 0 to limit the search depth
    """

    s = hex(addr)[2:].zfill(8)
    path = [s]
    currentFuncList = [set()]
    totalFuncList = set()
    currentDataRange = [[]]

    def navigate_tree(addr):
        nonlocal s
        newentry = ""
        stepinto = True
        endfunc = False

        while True:
            instr = mem_read(addr)

            # ldr rn, [pc, nn]; updates the local data range
            if 0x4800 <= instr < 0x5000:
                minmax(currentDataRange[-1], (addr+4 & ~2) + 4*(instr & 0xFF))

            # bl instructions
            elif 0xF000 <= instr < 0xF800 and mem_read(addr + 2) >= 0xF800:
                newaddr = addr + bl_offset(mem_read(addr, 4))
                newentry = f"{newaddr:0>8x}"
                addr += 2

            # bx instructions
            elif 0x4700 <= instr <= 0x4770:
                if instr <= 0x4738 and (instr & 0x38) >> 3 | 0x48 == ROM[(addr & 0xFFFFFF)-1]:  # if bx rn and last instr was ldr rn, [pc, nn]
                    newaddr = mem_read((addr+2 & ~2) + 4*ROM[(addr & 0xFFFFFF)-2], 4)
                    newentry = f"{newaddr-(newaddr&1):0>8x}"
                    if not (newaddr & 1 and newaddr>>27 & 1): stepinto = False # if it's not thumb, don't step into it
                    newaddr &= ~1
                endfunc = True

            # pop {pc}
            elif instr>>8 == 0xBD: endfunc = True
            
            if newentry and newentry not in currentFuncList[-1]:
                currentFuncList[-1].add(newentry)
                if len(currentFuncList[-1]) > 1:
                    print(s)
                    s = f"{' '*(len(path)*13-3)}|- {newentry}"
                else: 
                    s += " --- " + newentry

                # step into the new function recursively
                if stepinto and (depth == 0 or depth > len(path)) and newentry not in totalFuncList:
                    totalFuncList.add(newentry)
                    currentFuncList.append(set())
                    currentDataRange.append([])
                    path.append(newentry)
                    navigate_tree(newaddr)

            # return by exiting navigate_tree
            if endfunc:
                currentFuncList.pop()
                currentDataRange.pop()
                path.pop()
                break

            newentry = ""
            addr += 2
            if currentDataRange[-1] and addr >= min(currentDataRange[-1]): 
                addr = max(currentDataRange[-1]) + 4; currentDataRange[-1].clear()

    navigate_tree(addr)
    print(s)


def functionBounds(addr, mode=1):
    base = addr
    instrsize = 2 if mode==1 else 4
    value = mem_read(addr, instrsize)
    endfunc = 0
    if mode == 1:
        startcheck = lambda x: x & 0xff00 == 0xb500
        def endcheck(value):
            if value & 0xff00 == 0xbd00:
                return True
            elif value & 0xff80 == 0x4700:
                if value == 0x4770: return True
                reg = (value >> 3) & 7
                return mem_read(addr-2) & 0xffff == 0xbc00 | 2**reg
            else:
                return False
    elif mode == 0:
        startcheck = lambda x: x == 0x02004778 or x & 0x0F3F4000 == 0x092D4000
        endcheck = lambda x: x == 0xE12FFF1E or x & 0x0FBF8000 == 0x08BD8000
    while not startcheck(value): # search up for push {lr} instructions, or ends of functions
        addr -= instrsize
        value = mem_read(addr, instrsize)
        if endcheck(value):
            endfunc += 1
            if endfunc == 2: break
    start = addr
    while True:
        blcount = 0
        datarange = []
        addr = start
        value = mem_read(addr, instrsize)
        while not endcheck(value): # search down for pop {r0-r7, pc} or bx rn instructions
            if mode == 1:
                if value & 0xf800 == 0xf000: blcount += 1; addr += 2
                elif value & 0xf800 == 0x4800: minmax(datarange, (addr+4 & ~2) + 4*(value & 0xFF)) # update datarange for ldr rn, [pc, nn]
            elif mode == 0:
                if value & 0x0E9F0000 == 0x049F0000:
                    minmax(datarange, addr+8 + value & 0xFFF)
            addr += instrsize
            if datarange and addr >= min(datarange):  # if addr has entered datarange, count bl instructions and branch
                while addr < max(datarange) + 4:
                    if mode==1 and 0xf800f800 & mem_read(addr, 4) == 0xf800f000:
                        blcount += 1; addr += 2
                    addr += instrsize
                datarange.clear()
            value = mem_read(addr, instrsize)
        if addr >= base: break
        elif datarange: start = max(datarange) + 4
        else: start = addr + instrsize

    if mode==1: linecount = (addr-start)//2 + 1 - blcount
    elif mode==0: linecount = (addr-start)//4 + 1
    return start, addr, linecount
