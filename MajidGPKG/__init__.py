# [file name]: __init__.py
def classFactory(iface):
    from .majidgpkg import MajidGpkg
    return MajidGpkg(iface)