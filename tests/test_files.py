import asyncio
import binascii
import functools
import hashlib
import io
import os
import shutil
from datetime import datetime

import pytest

import py7zr
from py7zr import UnsupportedCompressionMethodError, unpack_7zarchive
from py7zr.helpers import UTC

from . import decode_all

testdata_path = os.path.join(os.path.dirname(__file__), 'data')
os.umask(0o022)


def check_archive(archive, tmp_path):
    assert sorted(archive.getnames()) == ['test', 'test/test2.txt', 'test1.txt']
    expected = []
    expected.append({'filename': 'test'})
    expected.append({'lastwritetime': 12786932616, 'as_datetime': datetime(2006, 3, 15, 21, 43, 36, 0, UTC()),
                     'filename': 'test/test2.txt'})
    expected.append({'lastwritetime': 12786932628, 'as_datetime': datetime(2006, 3, 15, 21, 43, 48, 0, UTC()),
                     'filename': 'test1.txt'})
    for i, cf in enumerate(archive.files):
        assert cf.filename == expected[i]['filename']
        if not cf.is_directory:
            assert cf.lastwritetime // 10000000 == expected[i]['lastwritetime']
            assert cf.lastwritetime.as_datetime().replace(microsecond=0) == expected[i]['as_datetime']
    archive.extractall(path=tmp_path)
    assert tmp_path.joinpath('test/test2.txt').open('rb').read() == bytes('This file is located in a folder.', 'ascii')
    assert tmp_path.joinpath('test1.txt').open('rb').read() == bytes('This file is located in the root.', 'ascii')


@pytest.mark.files
def test_solid(tmp_path):
    f = 'solid.7z'
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, '%s' % f), 'rb'))
    check_archive(archive, tmp_path)


@pytest.mark.files
def test_empty():
    # decompress empty archive
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'empty.7z'), 'rb'))
    assert archive.getnames() == []


@pytest.mark.files
def test_github_14(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'github_14.7z'), 'rb'))
    assert archive.getnames() == ['github_14']
    archive.extractall(path=tmp_path)
    with open(tmp_path.joinpath('github_14'), 'rb') as f:
        assert f.read() == bytes('Hello GitHub issue #14.\n', 'ascii')


@pytest.mark.files
def _test_umlaut_archive(filename):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, filename), 'rb'))
    assert sorted(archive.getnames()) == ['t\xe4st.txt']
    outbuf = []
    for i, cf in enumerate(archive.files):
        assert cf is not None
        buf = io.BytesIO()
        archive.worker.register_filelike(cf.id, buf)
        outbuf.append(buf)
    archive.worker.extract(archive.fp)
    buf = outbuf[0]
    buf.seek(0)
    actual = buf.read()
    assert actual == bytes('This file contains a german umlaut in the filename.', 'ascii')


@pytest.mark.files
def test_non_solid_umlaut():
    # test loading of a non-solid archive containing files with umlauts
    _test_umlaut_archive('umlaut-non_solid.7z')


@pytest.mark.files
def test_solid_umlaut():
    # test loading of a solid archive containing files with umlauts
    _test_umlaut_archive('umlaut-solid.7z')


@pytest.mark.files
def test_bugzilla_4(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'bugzilla_4.7z'), 'rb'))
    expected = [{'filename': 'History.txt', 'mtime': 1133704668, 'mode': 33188,
                 'digest': '46b08f0af612371860ab39e3b47666c3bd6fb742c5e8775159310e19ebedae7e'},
                {'filename': 'License.txt', 'mtime': 1105356710, 'mode': 33188,
                 'digest': '4f49a4448499449f2864777c895f011fb989836a37990ae1ca532126ca75d25e'},
                {'filename': 'copying.txt', 'mtime': 999116366, 'mode': 33188,
                 'digest': '2c3c3ef532828bcd42bb3127349625a25291ff5ae7e6f8d42e0fe9b5be836a99'},
                {'filename': 'readme.txt', 'mtime': 1133704646, 'mode': 33188,
                 'digest': '84f2693d9746e919883cf169fc83467be6566d7501b5044693a2480ab36a4899'}]
    decode_all(archive, expected, tmp_path)


@pytest.mark.files
def test_bugzilla_16(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'bugzilla_16.7z'), 'rb'))
    expected = [{'filename': 'mame4all_2.5.ini',
                 'digest': 'aaebca5e140e0099a757903fc9f194f9e6da388eed22d37bfd1625c80aa25903'},
                {'filename': 'mame4all_2.5/mame',
                 'digest': '6bc23b11fbb9a64096408623d476ad16083ef71c5e7919335e8696036034987d'}]
    decode_all(archive, expected, tmp_path)


@pytest.mark.files
def test_symlink(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'symlink.7z'), 'rb'))
    assert sorted(archive.getnames()) == ['lib', 'lib/libabc.so', 'lib/libabc.so.1', 'lib/libabc.so.1.2',
                                          'lib/libabc.so.1.2.3', 'lib64']
    archive.extractall(path=tmp_path)


@pytest.mark.files
def test_lzma2bcj(tmp_path):
    """Test extract archive compressed with LZMA2 and BCJ methods."""
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'lzma2bcj.7z'), 'rb'))
    assert archive.getnames() == ['5.12.1', '5.12.1/msvc2017_64',
                                  '5.12.1/msvc2017_64/bin', '5.12.1/msvc2017_64/bin/opengl32sw.dll']
    archive.extractall(path=tmp_path)
    m = hashlib.sha256()
    m.update(open(tmp_path.joinpath('5.12.1/msvc2017_64/bin/opengl32sw.dll'), 'rb').read())
    assert m.digest() == binascii.unhexlify('963641a718f9cae2705d5299eae9b7444e84e72ab3bef96a691510dd05fa1da4')


@pytest.mark.files
def test_zerosize(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'zerosize.7z'), 'rb'))
    archive.extractall(path=tmp_path)


@pytest.mark.api
def test_register_unpack_archive(tmp_path):
    shutil.register_unpack_format('7zip', ['.7z'], unpack_7zarchive)
    shutil.unpack_archive(os.path.join(testdata_path, 'test_1.7z'), tmp_path)
    target = os.path.join(tmp_path, "setup.cfg")
    expected_mode = 33188
    expected_mtime = 1552522033
    if os.name == 'posix':
        assert os.stat(target).st_mode == expected_mode
    assert os.stat(target).st_mtime == expected_mtime
    m = hashlib.sha256()
    m.update(open(target, 'rb').read())
    assert m.digest() == binascii.unhexlify('ff77878e070c4ba52732b0c847b5a055a7c454731939c3217db4a7fb4a1e7240')
    m = hashlib.sha256()
    m.update(open(os.path.join(tmp_path, 'setup.py'), 'rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update(open(os.path.join(tmp_path, 'scripts/py7zr'), 'rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')


@pytest.mark.files
def test_skip():
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'test_1.7z'), 'rb'))
    for i, cf in enumerate(archive.files):
        assert cf is not None
        archive.worker.register_filelike(cf.id, None)
    archive.worker.extract(archive.fp)


@pytest.mark.files
def test_github_14_multi(tmp_path):
    """ multiple unnamed objects."""
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'github_14_multi.7z'), 'rb'))
    assert archive.getnames() == ['github_14_multi', 'github_14_multi']
    archive.extractall(path=tmp_path)
    with open(os.path.join(tmp_path, 'github_14_multi'), 'rb') as f:
        assert f.read() == bytes('Hello GitHub issue #14 2/2.\n', 'ascii')


@pytest.mark.files
def test_multiblock(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'mblock_1.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    m = hashlib.sha256()
    m.update(open(os.path.join(tmp_path, 'bin/7zdec.exe'), 'rb').read())
    assert m.digest() == binascii.unhexlify('e14d8201c5c0d1049e717a63898a3b1c7ce4054a24871daebaa717da64dcaff5')


@pytest.mark.files
def test_multiblock_zerosize(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'mblock_2.7z'), 'rb'))
    archive.extractall(path=tmp_path)


@pytest.mark.files
@pytest.mark.timeout(5, method='thread')
def test_multiblock_last_padding(tmp_path):
    archive = py7zr.SevenZipFile(open(os.path.join(testdata_path, 'mblock_3.7z'), 'rb'))
    archive.extractall(path=tmp_path)
    m = hashlib.sha256()
    m.update(open(os.path.join(tmp_path, '5.13.0/mingw73_64/plugins/canbus/qtvirtualcanbusd.dll'), 'rb').read())
    assert m.digest() == binascii.unhexlify('98985de41ddba789d039bb10d86ea3015bf0d8d9fa86b25a0490044c247233d3')


@pytest.mark.files
@pytest.mark.xfail(raises=UnsupportedCompressionMethodError)
def test_copy(tmp_path):
    """ test loading of copy compressed files.(help wanted)"""
    check_archive(py7zr.SevenZipFile(open(os.path.join(testdata_path, 'copy.7z'), 'rb')), tmp_path)


@pytest.mark.files
def test_close_unlink(tmp_path):
    shutil.copyfile(os.path.join(testdata_path, 'test_1.7z'), tmp_path.joinpath('test_1.7z'))
    archive = py7zr.SevenZipFile(tmp_path.joinpath('test_1.7z'))
    archive.extractall(path=tmp_path)
    archive.close()
    os.unlink(tmp_path.joinpath('test_1.7z'))


def async_wrap(func):
    @asyncio.coroutine
    @functools.wraps(func)
    def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()
        partial_func = functools.partial(func, *args, **kwargs)
        return loop.run_in_executor(executor, partial_func)

    return run


aiounlink = async_wrap(os.unlink)


@asyncio.coroutine
def aio7zr(archive, path):
    loop = asyncio.get_event_loop()
    sevenzip = py7zr.SevenZipFile(archive)
    partial_py7zr = functools.partial(sevenzip.extractall, path=path)
    loop.run_in_executor(None, partial_py7zr)
    loop.run_in_executor(None, sevenzip.close)


@pytest.mark.files
def test_asyncio_executor_unlink(tmp_path):
    shutil.copyfile(os.path.join(testdata_path, 'test_1.7z'), tmp_path.joinpath('test_1.7z'))
    loop = asyncio.get_event_loop()
    unzip = asyncio.ensure_future(aio7zr(tmp_path.joinpath('test_1.7z'), path=tmp_path))
    loop.run_until_complete(unzip)
    loop.run_until_complete(aiounlink(tmp_path.joinpath('test_1.7z')))

