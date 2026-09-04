Page objects for the dimeshift application. Scripts to run test generation experiments.

### Run the application

Execute the Bash script to initialize the Docker image containing the web application:

`./run-docker.sh`

Inside the container, start the application server and MySQL:

`./run-services-docker.sh`

The application shall run at the address:

`http://localhost:3000`

### Admin Credentials
No user is pre-registered. In order to use the functionalities of the application a new user has to be registered.

### Stop application and remove container
Type `^C` in the terminal and then type `exit` to exit from the container. In order to remove the container type `docker rm $(docker ps -aq)`. The command will remove all stopped containers.

## Source revision provenance

The `dimeshift/` subdirectory is a git submodule pinned to

    https://github.com/jeka-kiselyov/dimeshift.git
    440898e8e48b9a85f4d3c7dfa374e4abd7e27423

That revision is the upstream's `master` head (verified 2026-09-04), and it is the same short SHA
that names the benchmark's Docker image tag — `webappdockers/dimeshift:440898e`, built by the
recipe in `dimeshift_change_versions`. The pin therefore records **which application revision the
image under test was built from**, which is the only reason it needs to exist: the application is
run from the Docker image, never from a source checkout, so the submodule is deliberately left
uninitialised.

`git submodule status` showing a `-` prefix for this path is the expected state.

### Repair note

Until 2026-09-04 this path was a gitlink with **no `.gitmodules` entry**, committed that way in
`e5ef8d2` ("added initial version of autoe2e and e2ebench"). Git had a submodule pointer it could
not resolve: `git submodule update` reported "no submodule mapping found", recursive clones left an
empty directory, and the recorded revision was unreachable in practice. The missing mapping was
added; the commit was not changed, so the recorded revision is exactly as it always was.
