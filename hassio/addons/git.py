"""Init file for HassIO addons git."""
import asyncio
import logging
import functools as ft
from pathlib import Path
import shutil

import git

from .utils import get_hash_from_repository
from ..const import URL_HASSIO_ADDONS, ATTR_URL, ATTR_BRANCH
from ..coresys import CoreSysAttributes
from ..validate import RE_REPOSITORY

_LOGGER = logging.getLogger(__name__)


class GitRepo(CoreSysAttributes):
    """Manage addons git repo."""

    def __init__(self, coresys, path, url):
        """Initialize git base wrapper."""
        self.coresys = coresys
        self.repo = None
        self.path = path
        self.lock = asyncio.Lock(loop=coresys.loop)

        self._data = RE_REPOSITORY.match(url).groupdict()

    @property
    def url(self):
        """Return repository URL."""
        return self._data[ATTR_URL]

    @property
    def branch(self):
        """Return repository branch."""
        return self._data[ATTR_BRANCH]

    async def load(self):
        """Init git addon repo."""
        if not self.path.is_dir():
            return await self.clone()

        async with self.lock:
            try:
                _LOGGER.info("Load addon %s repository", self.path)
                self.repo = await self.sys_run_in_executor(
                    git.Repo, str(self.path))

            except (git.InvalidGitRepositoryError, git.NoSuchPathError,
                    git.GitCommandError) as err:
                _LOGGER.error("Can't load %s repo: %s.", self.path, err)
                self._remove()
                return False

            return True

    async def clone(self):
        """Clone git addon repo."""
        async with self.lock:
            git_args = {
                attribute: value
                for attribute, value in (
                    ('recursive', True),
                    ('branch', self.branch),
                    ('depth', 1),
                    ('shallow-submodules', True)
                ) if value is not None
            }

            try:
                _LOGGER.info("Clone addon %s repository", self.url)
                self.repo = await self.sys_run_in_executor(ft.partial(
                    git.Repo.clone_from, self.url, str(self.path),
                    **git_args
                ))

            except (git.InvalidGitRepositoryError, git.NoSuchPathError,
                    git.GitCommandError) as err:
                _LOGGER.error("Can't clone %s repo: %s.", self.url, err)
                self._remove()
                return False

            return True

    async def pull(self):
        """Pull git addon repo."""
        if self.lock.locked():
            _LOGGER.warning("It is already a task in progress.")
            return False

        async with self.lock:
            _LOGGER.info("Update addon %s repository", self.url)
            branch = self.repo.active_branch.name

            try:
                # Download data
                await self.sys_run_in_executor(ft.partial(
                    self.repo.remotes.origin.fetch, **{
                        'update-shallow': True,
                        'depth': 1,
                    }))

                # Jump on top of that
                await self.sys_run_in_executor(ft.partial(
                    self.repo.git.reset, f"origin/{branch}", hard=True))

                # Cleanup old data
                await self.sys_run_in_executor(ft.partial(
                    self.repo.git.clean, "-xdf"))

            except (git.InvalidGitRepositoryError, git.NoSuchPathError,
                    git.GitCommandError) as err:
                _LOGGER.error("Can't update %s repo: %s.", self.url, err)
                return False

            return True

    def _remove(self):
        """Remove a repository."""
        if not self.path.is_dir():
            return

        def log_err(funct, path, _):
            """Log error."""
            _LOGGER.warning("Can't remove %s", path)

        shutil.rmtree(str(self.path), onerror=log_err)


class GitRepoHassIO(GitRepo):
    """HassIO addons repository."""

    def __init__(self, coresys):
        """Initialize git hassio addon repository."""
        super().__init__(
            coresys, coresys.config.path_addons_core, URL_HASSIO_ADDONS)


class GitRepoCustom(GitRepo):
    """Custom addons repository."""

    def __init__(self, coresys, url):
        """Initialize git hassio addon repository."""
        path = Path(
            coresys.config.path_addons_git,
            get_hash_from_repository(url))

        super().__init__(coresys, path, url)

    def remove(self):
        """Remove a custom repository."""
        _LOGGER.info("Remove custom addon repository %s", self.url)
        self._remove()
