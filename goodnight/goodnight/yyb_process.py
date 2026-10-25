"""Supervisor entry point: credentials stay in the private data volume."""
import os
from pathlib import Path
from .wechat import credentials


def main():
    os.umask(0o077)
    directory = Path(os.environ.get('DATA_DIR', '/app/data'))
    directory.mkdir(parents=True, exist_ok=True)
    auth = credentials(directory)
    os.environ.update(YYB_ADMIN_USER=auth['username'], YYB_ADMIN_PASSWORD=auth['password'],
                      YYB_PROTOCOL_TOKEN=auth['token'], YYB_AUTH_DRIVER='sqlite')
    os.execv('/usr/local/bin/yyb-go', ['yyb-go', '-host', '127.0.0.1', '-port', '8001',
               '-resource-root', str(directory / 'wechat')])


if __name__ == '__main__':
    main()
