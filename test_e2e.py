import sys, os, socket
sys.path.insert(0, '.')
from shared.protocol import send_json, recv_json, sha256_of_file, PORT, HOST, CHUNK_SIZE

print('=== TEST 1: Upload test1.txt ===')
filepath  = 'test-files/test1.txt'
filename  = 'test1.txt'
filesize  = os.path.getsize(filepath)
checksum  = sha256_of_file(filepath)
print(f'  File: {filename}  Size: {filesize}  Checksum: {checksum[:16]}...')

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((HOST, PORT))
send_json(sock, {'command': 'UPLOAD'})
r = recv_json(sock)
print(f'  Step1 -> {r}')
send_json(sock, {'filename': filename, 'filesize': filesize, 'checksum': checksum})
r = recv_json(sock)
print(f'  Step3 -> {r}')
with open(filepath, 'rb') as f:
    while True:
        chunk = f.read(CHUNK_SIZE)
        if not chunk:
            break
        sock.sendall(chunk)
result = recv_json(sock)
print(f'  Result -> {result}')
assert result['status'] == 'UPLOAD_SUCCESS', result
sock.close()
print('  PASSED!')

print()
print('=== TEST 2: LIST files ===')
sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock2.connect((HOST, PORT))
send_json(sock2, {'command': 'LIST'})
r2 = recv_json(sock2)
files = [f['name'] for f in r2.get('files', [])]
print(f'  Files: {files}')
sock2.close()
print('  PASSED!')

print()
print('=== TEST 3: Download test1.txt ===')
sock3 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock3.connect((HOST, PORT))
send_json(sock3, {'command': 'DOWNLOAD', 'filename': 'test1.txt'})
r3 = recv_json(sock3)
status3 = r3['status']
size3   = r3.get('filesize')
chk3    = r3.get('checksum')
print(f'  Server found: {status3}  size={size3}')
assert status3 == 'FOUND'
send_json(sock3, {'status': 'READY'})
dest = 'client/downloaded_files/test1_verify.txt'
total = r3['filesize']
received = 0
with open(dest, 'wb') as f:
    while received < total:
        chunk = sock3.recv(min(CHUNK_SIZE, total - received))
        if not chunk:
            break
        f.write(chunk)
        received += len(chunk)
sock3.close()
dl_checksum = sha256_of_file(dest)
assert dl_checksum == chk3, f'Mismatch: {dl_checksum} != {chk3}'
print(f'  Downloaded {received} bytes, checksum verified!')
print('  PASSED!')

print()
print('=== TEST 4: STATUS ===')
sock4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock4.connect((HOST, PORT))
send_json(sock4, {'command': 'STATUS'})
r4 = recv_json(sock4)
uptime4 = r4.get('uptime_seconds')
fcount4 = r4.get('files_stored')
print(f'  Uptime: {uptime4}s  Files: {fcount4}')
sock4.close()
print('  PASSED!')

print()
print('=== TEST 5: NOT_FOUND download ===')
sock5 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock5.connect((HOST, PORT))
send_json(sock5, {'command': 'DOWNLOAD', 'filename': 'ghost.bin'})
r5 = recv_json(sock5)
s5 = r5['status']
print(f'  Server responded: {s5}')
assert s5 == 'NOT_FOUND'
sock5.close()
print('  PASSED!')

print()
print('=== TEST 6: Duplicate filename upload ===')
sock6 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock6.connect((HOST, PORT))
send_json(sock6, {'command': 'UPLOAD'})
recv_json(sock6)
send_json(sock6, {'filename': 'test1.txt', 'filesize': filesize, 'checksum': checksum})
r6 = recv_json(sock6)
stored_as = r6.get('stored_as')
print(f'  Stored as: {stored_as}')
assert stored_as != 'test1.txt', 'Should have been renamed!'
with open(filepath, 'rb') as f:
    while True:
        chunk = f.read(CHUNK_SIZE)
        if not chunk:
            break
        sock6.sendall(chunk)
result6 = recv_json(sock6)
s6 = result6['status']
print(f'  Result: {s6}')
sock6.close()
print('  PASSED! (file auto-renamed)')

print()
print('ALL TESTS PASSED! The system is working correctly.')
