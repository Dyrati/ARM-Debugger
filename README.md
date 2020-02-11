# ARM Debugger
An easy to use, powerful debugger.  Import a rom, and an sgm file, and set breakpoints, watchpoints, and readpoints, view/modify registers and memory, output results to a txt file, and disassemble the code.

## Set Up
Make sure you have Python installed, and download the repository.  You can then unpack it and open "Debugger.py", and that's it!
From there, you can type in help or ? to get detailed info on the available commands.
You can also start Debugger.py from the command line with two optional arguments: `[filepath to rom] [filepath to savestate]`

#### Imports and Savestates
To execute instructions, you'll need to import a rom.  You can use the command `importrom [filepath]`.  You can upload savestate files in .sgm format using `importstate [filepath]`.  At any time, you may create a local save only available to the current session, using `save (identifier)` (identifier is PRIORSTATE by default), which can be loaded using `load (identifier)`.

## Variables
You can store variables by typing in [identifier] = [expression]
```
> test = 12345
```
Then you can use those variables in place of any arguments.  You can also modify variables with compound assignment operators. (+=, -=, \*=, etc).  "expression" may include any combination of variables and mathematical operations.

Default variables are r0-r16, which refer to the registers (r16 is PSR).  sp/lr/pc are r13/r14/r15, and m(addr,size) is *size* bytes of data at *addr* (size=4 by default).  These may be modified just like any other variable:
```
> i
R00: 08000000 R01: 000000EA R02: 00000000 R03: 00000000
R04: 00000000 R05: 00000000 R06: 00000000 R07: 00000000
R08: 00000000 R09: 00000000 R10: 00000000 R11: 00000000
R12: 00000000 R13: 03007F00 R14: 00000000 R15: 08000004
CPSR: [-ZC--] 6000001F
> r0 = sp+12
> i
R00: 03007F0C R01: 000000EA R02: 00000000 R03: 00000000
R04: 00000000 R05: 00000000 R06: 00000000 R07: 00000000
R08: 00000000 R09: 00000000 R10: 00000000 R11: 00000000
R12: 00000000 R13: 03007F00 R14: 00000000 R15: 08000004
CPSR: [-ZC--] 6000001F
```
You can use variable expressions as arguments.  If the command takes multiple arguments, then each expression must not contain spaces.
```
> chardata = $02000520
> m chardata+$14C*4 10
02000A50:  696C6546 00000078 00000000 05000000   Felix...........
02000A60:  00220046 3ACF4000 000C0020 0102001A   F."..@.: .......
02000A70:  00000000 0077006D                     ....m.w.
```
Expressions may be typed directly into to the console to print their value.  Hexadecimal numbers must be preceded by "0x", "$", or "x".

## Output
The output file is "output.txt"
Output is off by default.  By using the command `output true`, the registers and other data will be written to the file after each executed instruction.  You can pick a format preset using the `format` command.
