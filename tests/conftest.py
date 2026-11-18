import pytest

from samples.generate_samples import generate


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    # Never discover or copy real candidate reports from the parent workspace.
    return generate(tmp_path_factory.mktemp("synthetic_reports"))[:2]

