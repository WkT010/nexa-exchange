import pty, os, time, re, sys, select

master_fd, slave_fd = pty.openpty()
slave_name = os.ttyname(slave_fd)
print(f"PTY slave: {slave_name}", flush=True)

pid = os.fork()
if pid == 0:
    os.close(master_fd)
    os.setsid()
    os.close(slave_fd)
    s = os.open(slave_name, os.O_RDWR)
    try:
        os.tcsetpgrp(s, os.getpid())
    except Exception:
        pass
    os.dup2(s, 0)
    os.dup2(s, 1)
    os.dup2(s, 2)
    if s > 2:
        os.close(s)
    os.execvp('ssh', [
        'ssh', '-tt',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'ServerAliveInterval=60',
        '-o', 'ServerAliveCountMax=3',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ProxyCommand=nc -X connect -x 127.0.0.1:18080 %h %p',
        '-R', '80:localhost:8080',
        'serveo.net'
    ])
else:
    os.close(slave_fd)
    print(f"Child PID: {pid}", flush=True)
    
    output = b''
    deadline = time.time() + 20
    found = False
    
    while time.time() < deadline:
        try:
            r, _, _ = select.select([master_fd], [], [], 0.5)
            if r:
                data = os.read(master_fd, 4096)
                if data:
                    output += data
                    decoded = output.decode('utf-8', errors='replace')
                    urls = re.findall(r'https://[a-z0-9-]+\.serveousercontent\.com', decoded)
                    if urls:
                        print(f"URL_FOUND: {urls[-1]}", flush=True)
                        with open('/tmp/serveo-url.txt', 'w') as f:
                            f.write(urls[-1])
                        found = True
                        break
                    sys.stdout.write('.')
                    sys.stdout.flush()
                else:
                    break
            else:
                sys.stdout.write(',')
                sys.stdout.flush()
        except OSError as e:
            print(f"\nRead error: {e}", flush=True)
            break
        except Exception as e:
            print(f"\nError: {e}", flush=True)
            break
        time.sleep(0.2)
    
    print(flush=True)
    decoded = output.decode('utf-8', errors='replace')
    if found:
        print(f"SUCCESS: Tunnel established", flush=True)
    else:
        print(f"NO_URL. Output ({len(output)} bytes): {repr(decoded[:500])}", flush=True)
    
    with open('/tmp/serveo-tunnel-pid.txt', 'w') as f:
        f.write(str(pid))
    print(f"TUNNEL_PID: {pid}", flush=True)