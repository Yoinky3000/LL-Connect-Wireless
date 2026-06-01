# CLI Documentation

## `ll-connect-wireless`

```bash
usage: ll-connect-wireless [-h] [--print-completion {bash,zsh,tcsh}]
                           {help,info,update,status,enable,disable,start,stop,restart,monitor,uninstall,settings}
                           ...

LL-Connect-Wireless (LLCW) CLI (Version: 20260311.0745.4542)

positional arguments:
  {help,info,update,status,enable,disable,start,stop,restart,monitor,uninstall,settings}
                        Available commands
    help                same as -h/--help
    info                show app version info and changelog of llcw
    update              check and update llcw to latest version
    status              show systemd service status
    enable              enable llcw service and start it
    disable             disable llcw service
    start               start the llcw service
    stop                stop the llcw service
    restart             restart the llcw service
    monitor             show live fan monitor (Default to it if no command is
                        provided)
    uninstall           stop, disable and remove llcw
    settings            Manage settings

options:
  -h, --help            show this help message and exit
  --print-completion {bash,zsh,tcsh}
                        print shell completion script

'llcw' is also an alias command to 'll-connect-wireless'. You can also use
'll-connect-wireless' without arguments to see live monitor.
```

## `ll-connect-wireless settings`

```bash
usage: ll-connect-wireless settings [-h]
                                    {set-mode,reset,linear,curve,set-source,clear-sources,show-sources}
                                    ...

positional arguments:
  {set-mode,reset,linear,curve,set-source,clear-sources,show-sources}
    set-mode            set control mode
    reset               reset the settings
    linear              Linear mode settings
    curve               Curve mode settings
    set-source          assign fan(s) to a temperature source group (requires
                        running service)
    clear-sources       reset fan(s) back to CPU temperature source (requires
                        running service)
    show-sources        show temperature source group for each fan (requires
                        running service)

options:
  -h, --help            show this help message and exit
```

## `ll-connect-wireless settings linear`

```bash
usage: ll-connect-wireless settings linear [-h]
                                           {reset,reset-gpu-curve,set-curve,set-gpu-curve}
                                           ...

positional arguments:
  {reset,reset-gpu-curve,set-curve,set-gpu-curve}
    reset               reset linear curve
    reset-gpu-curve     reset GPU linear curve
    set-curve           set linear curve
    set-gpu-curve       set GPU linear curve

options:
  -h, --help            show this help message and exit
```

## `ll-connect-wireless settings curve`

```bash
usage: ll-connect-wireless settings curve [-h]
                                          {reset,set-cpu-curve,set-gpu-curve}
                                          ...

positional arguments:
  {reset,set-cpu-curve,set-gpu-curve}
    reset               reset CPU/GPU curves
    set-cpu-curve       set CPU curve
    set-gpu-curve       set GPU curve

options:
  -h, --help            show this help message and exit
```
