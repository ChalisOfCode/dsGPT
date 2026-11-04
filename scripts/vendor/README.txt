The SRT 3.5.3 wheel is included because PyPI publishes this version as a source
archive only. The Windows acceptance build can therefore use the same verified
pure-Python artifact without a package build or compiler on the user's PC.

requirements-windows.lock.json pins this wheel's SHA256 and size and the original
PyPI source URL, hash and size. Every Python module in the wheel was checked
byte-for-byte against that source archive. It was built with CPython 3.12 and
setuptools 84.2.1 using pip wheel --no-deps. The wheel includes its MIT license.
Its optional command-line scripts remain at their archive paths; dsGPT never
registers or executes them. Vosk uses the importable modules.
