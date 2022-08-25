import subprocess

def pull(target="."):
    cmd = "pushd {} && git pull && popd".format(target)
    print(cmd)
    subprocess.run(cmd)

def clone(url, into):
    cmd = "git clone {} {}".format(url, into if into else "")
    print(cmd)
    subprocess.run(cmd)