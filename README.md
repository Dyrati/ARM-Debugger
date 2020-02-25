# ARM Debugger
An easy to use, powerful debugger.  Import a rom, and an sgm file, and set breakpoints, watchpoints, and readpoints, view/modify registers and memory, output results to a txt file, disassemble the code, and more!


## Set Up
Make sure you have Python installed, and download the repository.  You can then unpack it and open "Debugger.py", and that's it!
From there, you can type in `help` or `?` to get detailed info on the available commands.
You can also start Debugger.py from the command line with two optional arguments: `[filepath to rom] [filepath to savestate]`

To execute CPU instructions, you'll need to import a rom.  You can use the command `importrom [filepath]`.  You can upload savestate files in .sgm format using `importstate [filepath]`.  At any time, you may create a local save only available to the current session, using `save (identifier)` (identifier is PRIORSTATE by default), which can be loaded using `load (identifier)`.

```
> importrom C:\Users\GenericName\Games\Roms\romname.gba
> importstate C:\Users\GenericName\Games\Saves\statename.sgm

# works with or without quotation marks, regardless of spaces in the path name, 
# so clicking and dragging a file to the command window will work after typing importrom/importstate
```

That's pretty much all you need to get started.  The rest of this readme is just here to explain some features.


## Basic Commands
- `n (count)` - execute *count* instruction(s), displaying the registers.  Count=1 by default.
- `c (count)` - execute *count* instruction(s). Count=infinity by default.
- `b [addr]` - set a breakpoint at *addr*.  CPU execution will halt after *addr* is executed.
    - if *addr* is "all", displays all break/write/readpoints
- `bw [addr]` - set a watchpoint.  CPU execution will halt after *addr* has been written to.
- `br [addr]` - set a readpoint.  CPU execution will halt after *addr* has been read from.
- `bc [condition]` - set a conditional breakpoint.  CPU execution will halt if *condition* is true.
- `d [addr]` - delete a breakpoint
    - if *addr* is "all", deletes all break/write/readpoints
- `dw [addr]` - delete a watchpoint
- `dr [addr]` - delete a readpoint
- `dc [index]` - delete a conditional breakpoint by index number
- `i` - print the CPU registers
- `dist [addr] (*count*)` - display *count* THUMB instructions starting from *addr*
- `disa [addr] (*count*)` - display *count* ARM instructions starting from *addr*
- `m [addr] (count) (size)` - display *count* units of *size* bytes of memory at *addr* (count=1, size=4 by default)

Enter in nothing to execute the previous command.  

Arguments are separated by spaces.  Arguments in brackets `[...]` are required, and parentheses `(...)` are optional.  
All commands accept [*expressions*](#expressions) as arguments, however if the command accepts multiple arguments, the expressions must not contain spaces.


## Expressions
With this debugger, you can utilize and modify registers and memory directly as though they were python variables.
You can assign values to variables by typing in: *name* = *expression*
```
test = 12345678   # creates a user variable named 'test'
```
Assigning a value to registers and memory is just as easy
```
r0 = test   # sets the actual register r0 equal to test
m($02000000) = r0   # sets the memory at $02000000 equal to r0
```
Default variables are **r0-r16, sp, lr, pc,** and **m(*addr*, *size*)**.  (size=4 by default).  r16 is CPSR  
There are also 4 global variables that may be accessed, but not directly modified:
- `MODE` - 0 if in ARM mode, 1 if in THUMB mode 
- `ADDR` - The current address
- `INSTR` - The next machine code instruction to be executed
- `CPUCOUNT` - The total number of CPU instructions executed since the beginning of the session

Attempts to modify these (or any other) global variables will instead create a User Variable with the same name.  
In [Execution Mode](#execution-mode), these and any other global variables may be modified.


You can also modify variables with compound assignment operators. (+=, -=, \*=, etc).  `m(r1) += r2`  
Expressions may include any combination of variables and mathematical operations.  
Expressions may be typed directly into to the console to print their value.  
Hexadecimal numbers must be preceded by "0x", "$", or "x". 
```
base = $08000000
m(base + 0xc, 8) = 4*r0 + r1*r2 - m(r3)//4
```
**You can use expressions in place of any arguments**

If the command takes multiple arguments, then each expression must not contain spaces.
```
> chardata = $02000520
> m chardata+$14C*4 10
02000A50:  696C6546 00000078 00000000 05000000   Felix...........
02000A60:  00220046 3ACF4000 000C0020 0102001A   F."..@.: .......
02000A70:  00000000 0077006D                     ....m.w.
```


## Higher Level Commands
- `if [condition]: [command]` - execute *command* if *condition* is true
- `while [condition]: [command]` - repeat *command* while *condition* is true
- `rep/repeat [count]: [command]` - repeat *command* *count* times
- `[name][op][expression]` - create/modify a User Variable
- `def [name]: [commands]`
    - bind a list of commands separated by semicolons to *name*
    - execute these functions later by typing in "*name*()"
    - you can call functions within functions, with unlimited nesting
- `save (name)` - create a local save; *name* = PRIORSTATE by default
- `load (name)` - load a local save; *name* = PRIORSTATE by default
- `dv [name]` - delete user variable
- `df [name]` - delete user function
- `ds (name)` - delete local save; *name* = PRIORSTATE by default
- `vars` - print all user variables
- `funcs` - print all user functions
- `saves` - print all local saves  

**You can write multiple commands in a single line by separating them with `;`**  
**You can use multiple-command if/while/repeat instructions by separating each inner command with `\`**  
(using a semicolon will end the if/while/repeat instruction)
```
> wram = $02000000; m wram 32 1
02000000:  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00   ................
02000010:  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00   ................
> iter = 0; rep 32: m(wram + iter) = iter \ iter += 1; m wram 32 1
02000000:  00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F   ................
02000010:  10 11 12 13 14 15 16 17 18 19 1A 1B 1C 1D 1E 1F   ................
> def clear: iter = 0; while iter < arg1: m(arg0 + iter, 1) = 0 \ iter += 1
> arg0 = wram; arg1 = 16; clear()
> m wram 32 1
02000000:  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00   ................
02000010:  10 11 12 13 14 15 16 17 18 19 1A 1B 1C 1D 1E 1F   ................
> funcs
{'clear': iter = 0; while iter < arg1: m(arg0 + iter, 1) = 0 \ iter += 1}
```

The commands may be anything, including function calls, loops, and even [Debugger Mode Swaps](#alternate-debugger-modes).  

`save` and `load` only apply to local saves.  Local saves are temporarily stored in the current session.  They can be given names and loaded with those names at any time.  To overwrite an actual savestate file, use `exportstate`.  


## File Commands
- `importrom [filepath]` - import a rom into the debugger
- `importstate [filepath]` - import a savestate
- `exportstate (filepath)` - save the current state to a file; 
    - *filepath* = (most recent import) by default
    - will overwrite the destination, back up your saves!
- `reset` - reset the emulator (clears the RAM and resets the registers)
- `output [condition]`
    - after each CPU instruction, if *condition* is True, the debugger will write data to "output.txt"
    - if *condition* is "clear", deletes all of the data in "output.txt"
- `format: [formatstr]` - set the format of data sent to the output file; see [Formats](#formats)

## Formats

Data sent to output.txt after each instruction may be formatted however you like.  You can choose what data to display, including data from memory, user expressions, global variables, or any of the preset values: `{addr}`, `{instr}`, `{asm}`, `{r0-r16}`, and `{cpsr}`

```
> output True
> format: example text {addr}: {instr}  {asm}\n  {r0-r3}
> c 3
```
Result in output.txt:
```
example text 08000000: EA000108  b $08000428
  R00: 08000000  R01: 000000EA  R02: 00000000  R03: 00000000
example text 08000428: E3A00012  mov r0, 0x12
  R00: 00000012  R01: 000000EA  R02: 00000000  R03: 00000000
example text 0800042C: E129F000  msr cpsr_fc, r0
  R00: 00000012  R01: 000000EA  R02: 00000000  R03: 00000000
```

**Interpolated values may optionally have a format specified with the following syntax: `{expression:format}`**
- Formats are in accordance with the 
  [Python Format Specification Mini-Language](https://docs.python.org/3/library/string.html#formatspec)  
- since the length of `{asm}` varies, I added an option to set its length with the syntax: `{asm:length}`
- for rlists, instead of the `{name:format}` syntax, you may use `{name:separator:format}`
    - `separator` refers to the ascii characters printed between each register in the rlist
- You may also use any of the following presets (default is "line"):
    - `line` = `{addr}: {instr}  {asm:20}  {cpsr}  {r0-r15}`
    - `block` = `{addr}: {instr}  {asm}\n  {r0-r3}\n  {r4-r7}\n  {r8-r11}\n  {r12-r15}\n  {cpsr}`
    - `linexl` = `{addr}:\t{instr}\t{asm:20}\t{cpsr}\t{r0-r15:\t}`
    - `blockxl` = `{addr}:\t{instr}\t{asm}\t\t{cpsr}\n\t{r0-r3:\t}\n\t{r4-r7:\t}\n\t{r8-r11:\t}\n\t{r12-r15:\t}\n\t{cpsr}`
```
> output true
> format: line
> c 5
```
Result in output.txt:
```
08000000: EA000108  b $08000428           CPSR: [-ZC--]  R00: 08000000  R01: 000000EA  R02: 00000000  R03: 00000000  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000  R12: 00000000  R13: 03007F00  R14: 00000000  R15: 0800042C
08000428: E3A00012  mov r0, 0x12          CPSR: [-ZC--]  R00: 00000012  R01: 000000EA  R02: 00000000  R03: 00000000  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000  R12: 00000000  R13: 03007F00  R14: 00000000  R15: 08000430
0800042C: E129F000  msr cpsr_fc, r0       CPSR: [-----]  R00: 00000012  R01: 000000EA  R02: 00000000  R03: 00000000  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000  R12: 00000000  R13: 03007F00  R14: 00000000  R15: 08000434
08000430: E59FD028  ldr sp, [$08000460]   CPSR: [-----]  R00: 00000012  R01: 000000EA  R02: 00000000  R03: 00000000  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000  R12: 00000000  R13: 03007FA0  R14: 00000000  R15: 08000438
08000434: E3A0001F  mov r0, 0x1f          CPSR: [-----]  R00: 0000001F  R01: 000000EA  R02: 00000000  R03: 00000000  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000  R12: 00000000  R13: 03007FA0  R14: 00000000  R15: 0800043C
```
```
> output clear
> format: block
> c 3
```
Result in output.txt:
```
08000438: E129F000  msr cpsr_fc, r0
  R00: 0000001F  R01: 000000EA  R02: 00000000  R03: 00000000
  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000
  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000
  R12: 00000000  R13: 03007FA0  R14: 00000000  R15: 08000440
  CPSR: [-----]

0800043C: E59FD018  ldr sp, [$0800045C] (=$03007F00)
  R00: 0000001F  R01: 000000EA  R02: 00000000  R03: 00000000
  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000
  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000
  R12: 00000000  R13: 03007F00  R14: 00000000  R15: 08000444
  CPSR: [-----]

08000440: E59F101C  ldr r1, [$08000464] (=$03007FFC)
  R00: 0000001F  R01: 03007FFC  R02: 00000000  R03: 00000000
  R04: 00000000  R05: 00000000  R06: 00000000  R07: 00000000
  R08: 00000000  R09: 00000000  R10: 00000000  R11: 00000000
  R12: 00000000  R13: 03007F00  R14: 00000000  R15: 08000448
  CPSR: [-----]
```
If viewing in Notepad, uncheck Word Wrap to make it look nicer.  
If viewing in Excel, try out `linexl` and `blockxl`.

## Alternate Debugger Modes
In addition to Normal Mode, there is Assembly Mode and Execution Mode. 
These Modes are indicated by the input prompt.
You can freely switch between these modes, including as part of function calls and loops.

### Assembly Mode
To enter Assembly Mode, type: `@` or `asm`.  
In this mode, you can type in Thumb Code, which is then immediately executed.  If the Thumb code is not recognized, it will attempt to execute the command in Normal Mode.  You do not need to already be in Thumb mode to execute the instruction.  
```
# display the registers

> i
R00: 00002553 R01: 030011BC R02: 6C3B3D69 R03: 00003039
R04: 080AD361 R05: 00002553 R06: 1E503FFC R07: 00000023
R08: 1E220000 R09: 080EE354 R10: 02030194 R11: 02030000
R12: 080C9F63 R13: 03007E2C R14: 080CA095 R15: 0801487C
CPSR: [----T] 0000003F
0801487A: 4B07      ldr r3, [$08014898] (=$41C64E6D)
```
```
# switch to Assembly Mode and branch to $08014878

> @
@ b $08014878
0801487A: E7FE      b $08014878
R00: 00002553 R01: 030011BC R02: 6C3B3D69 R03: 00003039
R04: 080AD361 R05: 00002553 R06: 1E503FFC R07: 00000023
R08: 1E220000 R09: 080EE354 R10: 02030194 R11: 02030000
R12: 080C9F63 R13: 03007E2C R14: 080CA095 R15: 0801487A
CPSR: [----T] 0000003F
```

### Execution Mode
To enter Execution Mode, type: `$` or `exec`.  
In this mode, you can type in real Python code, which is executed immediately.  
Here you have unrestrained access to all the global functions and variables of the script.  
User Expressions do not work in this mode.  The commands must be valid Python.  
Some useful commands in this mode include:
- `dir()` - displays all the global variable identifiers
- `UserVars, UserFuncs` - the user variables and user functions
- `OutputFormat` - shows how the current output format string was interpreted
- `CPUCOUNT` - tracking the cpucount helps a lot with troubleshooting; it can be modified in this mode
- `os, sys, traceback` - python modules

### Normal Mode
The default mode.  To reenter Normal Mode, type: `>` or `debug`.
