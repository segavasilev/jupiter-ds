# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import time
import logging

import pytest

LOGGER = logging.getLogger(__name__)


def test_cli_args(container, http_client):
    """Container should respect notebook server command line args
    (e.g., disabling token security)"""
    c = container.run(command=["start-notebook.sh", "--NotebookApp.token=''"])
    resp = http_client.get("http://localhost:8888")
    resp.raise_for_status()
    logs = c.logs(stdout=True).decode("utf-8")
    LOGGER.debug(logs)
    assert "ERROR" not in logs
    warnings = [
        warning for warning in logs.split("\n") if warning.startswith("WARNING")
    ]
    assert len(warnings) == 1
    assert warnings[0].startswith("WARNING: Jupyter Notebook deprecation notice")
    assert "login_submit" not in resp.text


@pytest.mark.filterwarnings("ignore:Unverified HTTPS request")
def test_unsigned_ssl(container, http_client):
    """Container should generate a self-signed SSL certificate
    and notebook server should use it to enable HTTPS.
    """
    c = container.run(environment=["GEN_CERT=yes"])
    # NOTE: The requests.Session backing the http_client fixture does not retry
    # properly while the server is booting up. An SSL handshake error seems to
    # abort the retry logic. Forcing a long sleep for the moment until I have
    # time to dig more.
    time.sleep(5)
    resp = http_client.get("https://localhost:8888", verify=False)
    resp.raise_for_status()
    assert "login_submit" in resp.text
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    warnings = [
        warning for warning in logs.split("\n") if warning.startswith("WARNING")
    ]
    assert len(warnings) == 1
    assert warnings[0].startswith("WARNING: Jupyter Notebook deprecation notice")


def test_uid_change(container):
    """Container should change the UID of the default user."""
    c = container.run(
        tty=True,
        user="root",
        environment=["NB_UID=1010"],
        command=["start.sh", "bash", "-c", "id && touch /opt/conda/test-file"],
    )
    # usermod is slow so give it some time
    rv = c.wait(timeout=120)
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert rv == 0 or rv["StatusCode"] == 0
    assert "uid=1010(sega)" in c.logs(stdout=True).decode("utf-8")


def test_gid_change(container):
    """Container should change the GID of the default user."""
    c = container.run(
        tty=True,
        user="root",
        environment=["NB_GID=110"],
        command=["start.sh", "id"],
    )
    rv = c.wait(timeout=10)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert "gid=110(sega)" in logs
    assert "groups=110(sega),100(users)" in logs


def test_nb_user_change(container):
    """Container should change the user name (`NB_USER`) of the default user."""
    nb_user = "nayvoj"
    running_container = container.run(
        tty=True,
        user="root",
        environment=[f"NB_USER={nb_user}", "CHOWN_HOME=yes"],
        command=["start.sh", "bash", "-c", "sleep infinity"],
    )

    # Give the chown time to complete. Use sleep, not wait, because the
    # container sleeps forever.
    time.sleep(10)
    LOGGER.info(f"Checking if the user is changed to {nb_user} by the start script ...")
    output = running_container.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in output
    assert "WARNING" not in output
    assert (
        f"username: sega       -> {nb_user}" in output
    ), f"User is not changed to {nb_user}"

    LOGGER.info(f"Checking {nb_user} id ...")
    command = "id"
    expected_output = f"uid=1000({nb_user}) gid=100(users) groups=100(users)"
    cmd = running_container.exec_run(command, user=nb_user, workdir=f"/home/{nb_user}")
    output = cmd.output.decode("utf-8").strip("\n")
    assert output == expected_output, f"Bad user {output}, expected {expected_output}"

    LOGGER.info(f"Checking if {nb_user} owns his home folder ...")
    command = f'stat -c "%U %G" /home/{nb_user}/'
    expected_output = f"{nb_user} users"
    cmd = running_container.exec_run(command, workdir=f"/home/{nb_user}")
    output = cmd.output.decode("utf-8").strip("\n")
    assert (
        output == expected_output
    ), f"Bad owner for the {nb_user} home folder {output}, expected {expected_output}"

    LOGGER.info(
        f"Checking if home folder of {nb_user} contains the hidden '.jupyter' folder with appropriate permissions ..."
    )
    command = f'stat -c "%F %U %G" /home/{nb_user}/.jupyter'
    expected_output = f"directory {nb_user} users"
    cmd = running_container.exec_run(command, workdir=f"/home/{nb_user}")
    output = cmd.output.decode("utf-8").strip("\n")
    assert (
        output == expected_output
    ), f"Hidden folder .jupyter was not copied properly to {nb_user} home folder. stat: {output}, expected {expected_output}"


def test_chown_extra(container):
    """Container should change the UID/GID of a comma separated
    CHOWN_EXTRA list of folders."""
    c = container.run(
        tty=True,
        user="root",
        environment=[
            "NB_UID=1010",
            "NB_GID=101",
            "CHOWN_EXTRA=/home/sega,/opt/conda/bin",
            "CHOWN_EXTRA_OPTS=-R",
        ],
        command=[
            "start.sh",
            "bash",
            "-c",
            "stat -c '%n:%u:%g' /home/sega/.bashrc /opt/conda/bin/jupyter",
        ],
    )
    # chown is slow so give it some time
    rv = c.wait(timeout=120)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert "/home/sega/.bashrc:1010:101" in logs
    assert "/opt/conda/bin/jupyter:1010:101" in logs


def test_chown_home(container):
    """Container should change the NB_USER home directory owner and
    group to the current value of NB_UID and NB_GID."""
    c = container.run(
        tty=True,
        user="root",
        environment=[
            "CHOWN_HOME=yes",
            "CHOWN_HOME_OPTS=-R",
            "NB_USER=kitten",
            "NB_UID=1010",
            "NB_GID=101",
        ],
        command=["start.sh", "bash", "-c", "stat -c '%n:%u:%g' /home/kitten/.bashrc"],
    )
    rv = c.wait(timeout=120)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert "/home/kitten/.bashrc:1010:101" in logs


def test_sudo(container):
    """Container should grant passwordless sudo to the default user."""
    c = container.run(
        tty=True,
        user="root",
        environment=["GRANT_SUDO=yes"],
        command=["start.sh", "sudo", "id"],
    )
    rv = c.wait(timeout=10)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert "uid=0(root)" in logs


def test_sudo_path(container):
    """Container should include /opt/conda/bin in the sudo secure_path."""
    c = container.run(
        tty=True,
        user="root",
        environment=["GRANT_SUDO=yes"],
        command=["start.sh", "sudo", "which", "jupyter"],
    )
    rv = c.wait(timeout=10)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert logs.rstrip().endswith("/opt/conda/bin/jupyter")


def test_sudo_path_without_grant(container):
    """Container should include /opt/conda/bin in the sudo secure_path."""
    c = container.run(
        tty=True,
        user="root",
        command=["start.sh", "which", "jupyter"],
    )
    rv = c.wait(timeout=10)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert logs.rstrip().endswith("/opt/conda/bin/jupyter")


def test_group_add(container):
    """Container should run with the specified uid, gid, and secondary
    group. It won't be possible to modify /etc/passwd since gid is nonzero, so
    additionally verify that setting gid=0 is suggested in a warning.
    """
    c = container.run(
        user="1010:1010",
        group_add=["users"],  # Ensures write access to /home/sega
        command=["start.sh", "id"],
    )
    rv = c.wait(timeout=5)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    warnings = [
        warning for warning in logs.split("\n") if warning.startswith("WARNING")
    ]
    assert len(warnings) == 1
    assert "Try setting gid=0" in warnings[0]
    assert "uid=1010 gid=1010 groups=1010,100(users)" in logs


def test_set_uid(container):
    """Container should run with the specified uid and NB_USER.
    The /home/sega directory will not be writable since it's owned by 1000:users.
    Additionally verify that "--group-add=users" is suggested in a warning to restore
    write access.
    """
    c = container.run(
        user="1010",
        command=["start.sh", "id"],
    )
    rv = c.wait(timeout=5)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "uid=1010(sega) gid=0(root)" in logs
    warnings = [
        warning for warning in logs.split("\n") if warning.startswith("WARNING")
    ]
    assert len(warnings) == 1
    assert "--group-add=users" in warnings[0]


def test_set_uid_and_nb_user(container):
    """Container should run with the specified uid and NB_USER."""
    c = container.run(
        user="1010",
        environment=["NB_USER=kitten"],
        group_add=["users"],  # Ensures write access to /home/sega
        command=["start.sh", "id"],
    )
    rv = c.wait(timeout=5)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "uid=1010(kitten) gid=0(root)" in logs
    warnings = [
        warning for warning in logs.split("\n") if warning.startswith("WARNING")
    ]
    assert len(warnings) == 1
    assert "user is kitten but home is /home/sega" in warnings[0]


def test_container_not_delete_bind_mount(container, tmp_path):
    """Container should not delete host system files when using the (docker)
    -v bind mount flag and mapping to /home/sega.
    """
    d = tmp_path / "data"
    d.mkdir()
    p = d / "foo.txt"
    p.write_text("some-content")

    c = container.run(
        tty=True,
        user="root",
        working_dir="/home/",
        environment=[
            "NB_USER=user",
            "CHOWN_HOME=yes",
        ],
        volumes={d: {"bind": "/home/sega/data", "mode": "rw"}},
        command=["start.sh", "ls"],
    )
    rv = c.wait(timeout=5)
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert rv == 0 or rv["StatusCode"] == 0
    assert p.read_text() == "some-content"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("enable_root", [False, True])
def test_jupyter_env_vars_to_unset_as_root(container, enable_root):
    """Environment variables names listed in JUPYTER_ENV_VARS_TO_UNSET
    should be unset in the final environment."""
    root_args = {"user": "root"} if enable_root else {}
    c = container.run(
        tty=True,
        environment=[
            "JUPYTER_ENV_VARS_TO_UNSET=SECRET_ANIMAL,UNUSED_ENV,SECRET_FRUIT",
            "FRUIT=bananas",
            "SECRET_ANIMAL=cats",
            "SECRET_FRUIT=mango",
        ],
        command=[
            "start.sh",
            "bash",
            "-c",
            "echo I like $FRUIT and ${SECRET_FRUIT:-stuff}, and love ${SECRET_ANIMAL:-to keep secrets}!",
        ],
        **root_args,
    )
    rv = c.wait(timeout=10)
    assert rv == 0 or rv["StatusCode"] == 0
    logs = c.logs(stdout=True).decode("utf-8")
    assert "ERROR" not in logs
    assert "WARNING" not in logs
    assert "I like bananas and stuff, and love to keep secrets!" in logs
