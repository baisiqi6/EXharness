"""Read-only, frozen Git inputs for consistency checks (standard library only)."""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from types import MappingProxyType


class SnapshotError(Exception):
    """The selected input or required history could not be proven complete."""


def match_path(path, patterns):
    """Match POSIX globs: '*' stays within a component; '**' spans components."""
    if isinstance(patterns, str):
        patterns = [patterns]
    parts = path.split("/")
    for pattern in patterns:
        while pattern.startswith("./"):
            pattern = pattern[2:]
        glob = pattern.split("/")

        @lru_cache(maxsize=None)
        def matches(i, j):
            if j == len(glob):
                return i == len(parts)
            if glob[j] == "**":
                return matches(i, j + 1) or (i < len(parts) and matches(i + 1, j))
            return i < len(parts) and fnmatchcase(parts[i], glob[j]) and matches(i + 1, j + 1)

        if matches(0, 0):
            return True
    return False


@dataclass(frozen=True)
class Entry:
    mode: str
    oid: str
    kind: str


@dataclass(frozen=True)
class Snapshot:
    entries: object
    revision: object
    tree: object
    kind: str
    _contents: object

    def __post_init__(self):
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))
        object.__setattr__(self, "_contents", MappingProxyType(dict(self._contents)))

    def read(self, path):
        """Return exact frozen blob bytes; missing paths and gitlinks have no blob."""
        return self._contents.get(path)

    def digest(self, patterns, exclude=()):
        """Hash a versioned, unambiguous projection of paths, modes and objects."""
        digest = hashlib.sha256(b"exharness-source-projection-v1\0")
        for path in sorted(self.entries):
            if not match_path(path, patterns) or match_path(path, exclude):
                continue
            entry = self.entries[path]
            for value in (path, entry.mode, entry.kind, entry.oid):
                data = value.encode("utf-8", "surrogateescape")
                digest.update(str(len(data)).encode("ascii") + b":" + data)
        return digest.hexdigest()

    def changed(self, other):
        return sorted(path for path in self.entries.keys() | other.entries.keys()
                      if self.entries.get(path) != other.entries.get(path))

    @property
    def identity(self):
        return "sha256:" + self.digest(["**"])


def _stat_key(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _fingerprint(path):
    try:
        before = path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SnapshotError(f"Cannot read Git metadata: {path}") from exc
    try:
        data = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise SnapshotError("Git index disappeared or became unreadable") from exc
    if _stat_key(before) != _stat_key(after):
        raise SnapshotError("Git index changed while being read")
    return _stat_key(after), hashlib.sha256(data).digest()


class GitRepo:
    def __init__(self, path):
        self.root = Path(path).resolve()
        self._env = dict(os.environ)
        # Do not let a read-only check refresh the index, fetch a promisor object,
        # prompt for credentials or substitute replacement history.
        self._env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1",
                         GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
        if self._env.get("GIT_INDEX_FILE"):
            self._env["GIT_INDEX_FILE"] = str(Path(self._env["GIT_INDEX_FILE"]).absolute())
        root = self._run(["rev-parse", "--show-toplevel"]).stdout.rstrip(b"\r\n")
        self.root = Path(os.fsdecode(root)).resolve()
        self._object_format = self._run(["rev-parse", "--show-object-format"]).stdout.strip().decode("ascii")
        if self._object_format not in {"sha1", "sha256"}:
            raise SnapshotError("Unsupported Git object format")
        self._gitdir = Path(os.fsdecode(self._run(["rev-parse", "--absolute-git-dir"]).stdout.rstrip(b"\r\n")))
        self._blob_cache = {}

    def _run(self, args, *, data=None, allowed=(0,), cwd=None, env=None):
        try:
            result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.commitGraph=false", *args],
                                    cwd=cwd or self.root, env=env or self._env,
                                    input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise SnapshotError("Cannot execute Git for the selected worktree") from exc
        if result.returncode not in allowed:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise SnapshotError(f"Git {args[0]} failed: {detail}")
        return result

    def _resolve(self, ref, suffix=""):
        if not isinstance(ref, str) or not ref or "\0" in ref:
            raise SnapshotError("A nonempty Git revision is required")
        return self._run(["rev-parse", "--verify", "--end-of-options", ref + suffix]).stdout.strip().decode("ascii")

    def _commit(self, ref):
        oid = self._resolve(ref, "^{commit}")
        # rev-parse alone can resolve an existing ref to an absent object.
        self._run(["cat-file", "-e", oid + "^{commit}"])
        return oid

    def head(self):
        return self._commit("HEAD")

    def _blobs(self, entries):
        required = {entry.oid for entry in entries.values() if entry.kind == "blob"}
        oids = sorted(required - self._blob_cache.keys())
        if not oids:
            return {path: self._blob_cache[entry.oid] for path, entry in entries.items()
                    if entry.kind == "blob"}
        output = self._run(["cat-file", "--batch"],
                           data=("\n".join(oids) + "\n").encode("ascii")).stdout
        offset, blobs = 0, {}
        for oid in oids:
            end = output.find(b"\n", offset)
            header = output[offset:end].split() if end >= 0 else []
            if len(header) != 3 or header[0] != oid.encode("ascii") or header[1] != b"blob":
                raise SnapshotError(f"Missing or invalid blob object {oid}")
            try:
                size = int(header[2])
            except ValueError as exc:
                raise SnapshotError("Invalid Git blob response") from exc
            start = end + 1
            offset = start + size + 1
            if size < 0 or offset > len(output) or output[offset - 1:offset] != b"\n":
                raise SnapshotError("Incomplete Git blob response")
            blobs[oid] = output[start:start + size]
        self._blob_cache.update(blobs)
        return {path: self._blob_cache[entry.oid] for path, entry in entries.items() if entry.kind == "blob"}

    def snapshot(self, ref):
        oid = self._resolve(ref, "^{}")
        kind = self._run(["cat-file", "-t", oid]).stdout.strip().decode("ascii")
        if kind not in {"commit", "tree"}:
            raise SnapshotError("Snapshot revision must identify a commit or tree")
        revision = oid if kind == "commit" else None
        tree = self._resolve(oid, "^{tree}")
        listing = self._run(["ls-tree", "-r", "-z", "--full-tree", tree]).stdout
        entries = {}
        for record in listing.split(b"\0"):
            if record:
                header, path = record.split(b"\t", 1)
                mode, object_kind, object_id = header.decode("ascii").split()
                entries[os.fsdecode(path)] = Entry(mode, object_id, object_kind)
        return Snapshot(entries, revision, tree, kind, self._blobs(entries))

    def _git_path(self, name):
        return Path(os.fsdecode(self._run(["rev-parse", "--path-format=absolute", "--git-path", name]).stdout.rstrip(b"\r\n")))

    def _index_fingerprint(self):
        index = self._git_path("index")
        first = _fingerprint(index)
        shared = sorted(set(self._gitdir.glob("sharedindex.*")) | set(index.parent.glob("sharedindex.*")))
        result = (index, first, tuple((path, _fingerprint(path)) for path in shared))
        if _fingerprint(index) != first:
            raise SnapshotError("Git index changed while being read")
        return result

    def _index_listing(self, args, fingerprint, *, data=None):
        # Git freshens split-index mtimes even when optional locks are disabled.
        # Parse copies instead, while keeping object/config/ignore semantics.
        index, state, shared = fingerprint

        def quoted(path):
            return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'

        with tempfile.TemporaryDirectory(prefix="exharness-index-") as temporary:
            gitdir = Path(temporary)
            (gitdir / "refs").mkdir()
            (gitdir / "objects").mkdir()
            (gitdir / "HEAD").write_text("ref: refs/heads/snapshot\n", encoding="ascii")
            # Repository discovery reads format extensions before includes.
            config = "[core]\n\trepositoryformatversion = " + ("1" if self._object_format == "sha256" else "0") + "\n"
            if self._object_format == "sha256":
                config += "[extensions]\n\tobjectformat = sha256\n"
            config += "[include]\n\tpath = " + quoted(self._git_path("config")) + "\n"
            work_config = self._gitdir / "config.worktree"
            if work_config.exists():
                config += "[include]\n\tpath = " + quoted(work_config) + "\n"
            (gitdir / "config").write_text(config, encoding="utf-8")
            for name in ("exclude", "attributes"):
                source = self._git_path("info/" + name)
                if source.exists():
                    (gitdir / "info").mkdir(exist_ok=True)
                    (gitdir / "info" / name).write_bytes(source.read_bytes())
            for source, expected in [(index, state), *shared]:
                if expected is None:
                    continue
                try:
                    index_data = source.read_bytes()
                except OSError as exc:
                    raise SnapshotError("Git index changed while copying its input") from exc
                if hashlib.sha256(index_data).digest() != expected[1]:
                    raise SnapshotError("Git index changed while copying its input")
                # The primary index always wins over an alternate index basename.
                destination = gitdir / ("index" if source == index else source.name)
                if source.parent == self._gitdir or not destination.exists():
                    destination.write_bytes(index_data)
            env = {**self._env, "GIT_DIR": str(gitdir), "GIT_COMMON_DIR": str(gitdir),
                   "GIT_WORK_TREE": str(self.root), "GIT_INDEX_FILE": str(gitdir / "index"),
                   "GIT_OBJECT_DIRECTORY": str(self._git_path("objects"))}
            return self._run(args, env=env, data=data).stdout

    def index(self):
        before = self._index_fingerprint()
        listing = self._index_listing(["ls-files", "--stage", "--debug", "-z"], before)
        offset, entries = 0, {}
        while offset < len(listing):
            end = listing.find(b"\0", offset)
            if end < 0:
                raise SnapshotError("Incomplete index listing")
            header, path = listing[offset:end].split(b"\t", 1)
            mode, oid, stage = header.decode("ascii").split()
            debug = re.match(rb"  ctime: [^\n]*\n  mtime: [^\n]*\n  dev: [^\n]*\n  uid: [^\n]*\n  size: [^\n]*\tflags: ([0-9a-fA-F]+)\n", listing[end + 1:])
            if not debug:
                raise SnapshotError("Cannot prove index entry flags")
            offset = end + 1 + debug.end()
            if stage != "0":
                raise SnapshotError("Unmerged index cannot be checked")
            if int(debug[1], 16) & 0x20000000 or not oid.strip("0"):
                raise SnapshotError("Intent-to-add index entry has no staged source")
            path = os.fsdecode(path)
            if mode not in {"100644", "100755", "120000", "160000"}:
                raise SnapshotError(f"Unsupported index mode {mode}")
            entries[path] = Entry(mode, oid, "commit" if mode == "160000" else "blob")
        contents = self._blobs(entries)
        if before != self._index_fingerprint():
            raise SnapshotError("Git index changed while being read")
        return Snapshot(entries, None, None, "index", contents)

    def _working_paths(self, fingerprint):
        listing = self._index_listing(["ls-files", "--cached", "--others", "--exclude-standard", "-z"], fingerprint)
        return sorted({os.fsdecode(path) for path in listing.split(b"\0") if path})

    def _physical_stat(self, path, ancestors=None):
        # A symlink replacing a tracked directory deletes its cached children;
        # following it would accidentally read files outside this worktree.
        parts = path.split("/")
        for size in range(1, len(parts) + 1):
            relative = "/".join(parts[:size])
            try:
                info = (self.root / relative).lstat()
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise SnapshotError(f"Cannot inspect worktree path {relative}") from exc
            if size == len(parts):
                return info
            if ancestors is not None:
                ancestors.setdefault(relative, _stat_key(info))
            if not stat.S_ISDIR(info.st_mode):
                return None

    def _config_bool(self, name):
        result = self._run(["config", "--bool", "--get", name], allowed=(0, 1))
        return result.stdout.strip() != b"false"

    def _config_value(self, name):
        result = self._run(["config", "--get", name], allowed=(0, 1))
        return result.stdout.rstrip(b"\r\n") if result.returncode == 0 else None

    def _conversion_metadata(self, fingerprint, paths):
        # These Git inspection commands neither run clean/process filters nor
        # convert record bytes. Git supplies its own text/binary classification.
        listing = self._index_listing(["ls-files", "--eol", "--cached", "--others",
                                       "--exclude-standard", "-z"], fingerprint)
        eols = {}
        for record in listing.split(b"\0"):
            if not record:
                continue
            header, path = record.split(b"\t", 1)
            match = re.fullmatch(rb"i/(\S*)\s+w/(\S*)\s+attr/(.*?)\s*", header)
            if match is None:
                raise SnapshotError("Cannot prove Git text/EOL conversion metadata")
            eols[os.fsdecode(path)] = tuple(value.decode("ascii") for value in match.groups())
        names = ("filter", "working-tree-encoding", "ident")
        raw = self._index_listing(["check-attr", "-z", "--stdin", *names], fingerprint,
                                  data=b"".join(os.fsencode(path) + b"\0" for path in paths))
        fields = raw.split(b"\0")
        if fields[-1:] != [b""] or (len(fields) - 1) % 3:
            raise SnapshotError("Incomplete Git conversion attribute metadata")
        attributes = {}
        drivers = {}
        for offset in range(0, len(fields) - 1, 3):
            path, name, value = (os.fsdecode(field) for field in fields[offset:offset + 3])
            attributes.setdefault(path, {})[name] = value
            if name == "filter" and value not in {"unspecified", "unset", "set"} and value not in drivers:
                drivers[value] = tuple(self._config_value("filter." + value + "." + setting)
                                       for setting in ("clean", "process", "required"))
        return eols, attributes, drivers, self._config_value("core.autocrlf")

    @staticmethod
    def _source_bytes(path, data, staged, metadata):
        eols, attributes, drivers, autocrlf = metadata
        attrs = attributes.get(path, {})
        if len(attrs) != 3 or path not in eols:
            raise SnapshotError(f"Missing worktree conversion metadata for {path}")
        if any(attrs[name] not in {"unspecified", "unset"} for name in ("working-tree-encoding", "ident")):
            raise SnapshotError(f"Unsupported worktree byte transformation for {path}")
        driver = drivers.get(attrs["filter"])
        if driver is not None:
            clean, process, required = driver
            if clean is not None or process is not None or (required is not None and required.lower() not in {b"false", b"no", b"off", b"0"}):
                raise SnapshotError(f"Custom worktree filter cannot be executed for {path}")
        _, working_eol, attribute = eols[path]
        if attribute == "-text":
            return data
        if attribute.startswith("text=auto"):
            automatic = True
        elif attribute == "text" or attribute.startswith("text "):
            automatic = False
        elif not attribute:
            if autocrlf is None or autocrlf.lower() in {b"false", b"no", b"off", b"0"}:
                return data
            automatic = True
        else:
            raise SnapshotError(f"Unsupported Git text/EOL attributes for {path}")
        if automatic and (working_eol == "-text" or b"\r\n" in (staged.read(path) or b"")):
            return data
        return data.replace(b"\r\n", b"\n")

    def worktree(self):
        before = self._index_fingerprint()
        staged = self.index()
        paths = self._working_paths(before)
        flags = self._index_listing(["ls-files", "-v", "-z"], before)
        sparse = {os.fsdecode(record[2:]) for record in flags.split(b"\0")
                  if record[:1].upper() == b"S"}
        entries, contents, states = {}, {}, {}
        gitlinks = {}
        filemode = self._config_bool("core.filemode")
        symlinks = self._config_bool("core.symlinks")
        for path in paths:
            full = self.root / path
            info = self._physical_stat(path, states)
            if info is None:
                if path in sparse:
                    raise SnapshotError(f"Sparse worktree content is unavailable: {path}")
                states[path] = None
                continue
            states[path] = _stat_key(info)
            indexed = staged.entries.get(path)
            try:
                if indexed and indexed.kind == "commit" and stat.S_ISDIR(info.st_mode):
                    oid = indexed.oid
                    if (full / ".git").exists():
                        subroot = self._run(["rev-parse", "--show-toplevel"], cwd=full).stdout.rstrip(b"\r\n")
                        if Path(os.fsdecode(subroot)).resolve() != full.resolve():
                            raise SnapshotError(f"Cannot identify gitlink worktree {path}")
                        oid = self._run(["rev-parse", "--verify", "HEAD^{commit}"], cwd=full).stdout.strip().decode("ascii")
                        self._run(["cat-file", "-e", oid + "^{commit}"], cwd=full)
                        gitlinks[path] = oid
                    entries[path] = Entry("160000", oid, "commit")
                    continue
                if stat.S_ISLNK(info.st_mode):
                    data, mode = os.fsencode(os.readlink(full)), "120000"
                elif stat.S_ISREG(info.st_mode):
                    data = full.read_bytes()
                    mode = "100755" if info.st_mode & 0o111 else "100644"
                    if indexed and indexed.mode in {"100644", "100755"} and not filemode:
                        mode = indexed.mode
                    if indexed and indexed.mode == "120000" and not symlinks:
                        mode = "120000"
                else:
                    raise SnapshotError(f"Unsupported worktree entry {path}")
            except OSError as exc:
                raise SnapshotError(f"Cannot read worktree path {path}") from exc
            oid = hashlib.new(self._object_format, b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
            entries[path] = Entry(mode, oid, "blob")
            contents[path] = data
        regular = sorted(path for path, entry in entries.items() if entry.mode in {"100644", "100755"})
        metadata = self._conversion_metadata(before, regular)
        for path in regular:
            source = self._source_bytes(path, contents[path], staged, metadata)
            oid = hashlib.new(self._object_format, b"blob " + str(len(source)).encode("ascii") + b"\0" + source).hexdigest()
            entries[path] = Entry(entries[path].mode, oid, "blob")
        if metadata != self._conversion_metadata(before, regular):
            raise SnapshotError("Git conversion attributes changed while reading the worktree")
        for path, previous in states.items():
            info = self._physical_stat(path)
            current = _stat_key(info) if info is not None else None
            if current != previous:
                raise SnapshotError(f"Worktree changed while reading {path}")
        for path, oid in gitlinks.items():
            if self._run(["rev-parse", "--verify", "HEAD^{commit}"], cwd=self.root / path).stdout.strip().decode("ascii") != oid:
                raise SnapshotError(f"Gitlink changed while reading {path}")
        if paths != self._working_paths(before) or before != self._index_fingerprint():
            raise SnapshotError("Worktree or index changed while being read")
        return Snapshot(entries, None, None, "worktree", contents)

    def _parent_ids(self, commit):
        oid = self._commit(commit)
        raw = self._run(["cat-file", "commit", oid]).stdout
        return [line[7:].decode("ascii") for line in raw.split(b"\n\n", 1)[0].splitlines()
                if line.startswith(b"parent ")]

    def parents(self, commit):
        return [self._commit(parent) for parent in self._parent_ids(commit)]

    def parent(self, commit):
        parents = self._parent_ids(commit)
        return self._commit(parents[0]) if parents else None

    def first_parent(self, start, tip, limit=2000):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise SnapshotError("History scan limit must be a positive integer")
        start, tip = self._commit(start), self._commit(tip)
        if start == tip:
            return []
        commits = self._run(["rev-list", "--first-parent", "--max-count=" + str(limit + 1),
                             tip, "^" + start, "--"]).stdout.decode("ascii").splitlines()
        if commits and len(commits) <= limit and self.parent(commits[-1]) == start:
            return list(reversed(commits))
        raise SnapshotError("Start is not provable on first-parent history within the scan limit")

    def is_ancestor(self, a, b):
        a, b = self._commit(a), self._commit(b)
        result = self._run(["merge-base", "--is-ancestor", a, b], allowed=(0, 1))
        if result.returncode == 0:
            return True
        if self._run(["rev-parse", "--is-shallow-repository"]).stdout.strip() == b"true":
            raise SnapshotError("Shallow history cannot prove non-ancestry")
        return False
