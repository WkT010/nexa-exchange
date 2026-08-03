import pty, os, time, re, sys, select, subprocess, signal

# Use a simpler approach: spawn SSH via subprocess with PTY
try:
    # Create PTY
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    print(f"PTY: master={master_fd}, slave={slave_name}", flush=True)
    
    # Build SSH command
    ssh_cmd = [
        'ssh', '-tt',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'ServerAliveInterval=60',
        '-o', 'ServerAliveCountMax=3',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ProxyCommand=nc -X connect -x 127.0.0.1:18080 %h %p',
        '-R', '80:localhost:8080',
        'serveo.net'
    ]
    
    # Fork and exec
    pid = os.fork()
    if pid == 0:
        # Child
        os.close(master_fd)
        os.setsid()
        
        # Open slave PTY
        sl = os.open(slave_name, os.O_RDWR)
        try:
            os.tcsetpgrp(sl, os.getpid())
        except:
            pass
        
        # Set stdin/stdout/stderr to slave PTY
        os.dup2(sl, 0)
        os.dup2(sl, 1)
        os.dup2(sl, 2)
        if sl > 2:
            os.close(sl)
        
        # Clear any PATH issues
        os.environ['PATH'] = '/usr/bin:/bin:/usr/local/bin'
        
        # Execute SSH
        os.execvp('ssh', ssh_cmd)
        # If we get here, exec failed
        sys.exit(1)
    else:
        # Parent - read from master
        os.close(slave_fd)
        print(f"SSH PID: {pid}", flush=True)
        
        # Set master to non-blocking
        import fcntl
        fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        
        output = b''
        deadline = time.time() + 20
        
        while time.time() < deadline:
            try:
                data = os.read(master_fd, 4096)
                if data:
                    output += data
                    decoded = output.decode('utf-8', errors='replace')
                    urls = re.findall(r'https://[a-z0-9-]+\.serveousercontent\.com', decoded)
                    if urls:
                        print(f"\nURL_FOUND: {urls[-1]}", flush=True)
                        with open('/tmp/serveo-url.txt', 'w') as f:
                            f.write(urls[-1])
                        break
                    # Print progress
                    sys.stdout.write('#')
                    sys.stdout.flush()
                else:
                    time.sleep(0.3)
            except BlockingIOError:
                time.sleep(0.3)
            except OSError:
                break
        
        print(flush=True)
        decoded = output.decode('utf-8', errors='replace')
        urls = re.findall(r'https://[a-z0-9-]+\.serveousercontent\.com', decoded)
        if urls:
            print(f"TUNNEL_OK: {urls[-1]}", flush=True)
        else:
            print(f"NO_URL. Bytes received: {len(output)}", flush=True)
            if output:
                print(f"Content: {repr(decoded[:600])}", flush=True)
        
        # Check if child is still running
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid == 0:
                print(f"SSH still running (pid={pid})", flush=True)
                with open('/tmp/serveo-tunnel-pid.txt', 'w') as f:
                    f.write(str(pid))
            else:
                print(f"SSH exited with status {status}", flush=True)
        except:
            pass
        
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()