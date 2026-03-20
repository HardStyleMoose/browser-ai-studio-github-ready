"""Adapt AI training and execution for different applications."""

from abc import ABC, abstractmethod


class ApplicationAdapter(ABC):
    """Abstract base for application adapters."""

    @abstractmethod
    def launch(self, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def capture_frame(self):
        raise NotImplementedError

    @abstractmethod
    def teardown(self):
        raise NotImplementedError
