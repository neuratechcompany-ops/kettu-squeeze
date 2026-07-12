"""v0.4 Dedup Engine tests."""
import pytest
from kettu_squeeze.dedup.engine import SessionDedup, DedupRef, ModelFacingPayload


class TestDedupRef:
    def test_short_format(self):
        ref = DedupRef(hash_key="abc123def456")
        assert "§k:" in ref.short()
        assert len(ref.short()) <= 12

    def test_token_estimate(self):
        ref = DedupRef(hash_key="abc123")
        assert len(ref) == 4


class TestSessionDedup:
    @pytest.fixture
    def dedup(self):
        return SessionDedup()

    def test_first_lookup_miss(self, dedup):
        assert dedup.lookup("hello") is None

    def test_second_lookup_hit(self, dedup):
        dedup.store("hello")
        ref = dedup.lookup("hello")
        assert ref is not None
        assert "§k:" in ref.short()

    def test_dedup_returns_short_ref(self, dedup):
        dedup.store("content")
        result, was_dedup = dedup.dedup("content")
        assert was_dedup
        assert "§k:" in result

    def test_dedup_first_returns_content(self, dedup):
        result, was_dedup = dedup.dedup("new content")
        assert not was_dedup
        assert result == "new content"

    def test_hit_rate(self, dedup):
        dedup.dedup("a")
        dedup.dedup("a")
        dedup.dedup("b")
        assert dedup.hit_rate == 1/3

    def test_clear_resets(self, dedup):
        dedup.store("x")
        dedup.clear()
        assert dedup.lookup("x") is None
        assert dedup.hits == 0

    def test_normalized_dedup(self, dedup):
        dedup.dedup("2026-07-12 10:00:00 ERROR: fail")
        result, was_dedup = dedup.dedup("2026-07-12 10:00:01 ERROR: fail")
        assert was_dedup  # different timestamp, same content after normalization

    def test_different_content_not_deduped(self, dedup):
        dedup.dedup("ERROR: a")
        result, was_dedup = dedup.dedup("ERROR: b")
        assert not was_dedup

    def test_lru_eviction(self):
        dedup = SessionDedup(max_entries=3)
        dedup.store("a"); dedup.store("b"); dedup.store("c"); dedup.store("d")
        assert dedup.lookup("a") is None  # evicted
        assert dedup.lookup("d") is not None


class TestModelFacingPayload:
    @pytest.fixture
    def mfp(self):
        return ModelFacingPayload()

    def test_wrap_minimal(self, mfp):
        result = mfp.wrap("compressed content")
        assert "compressed content" in result

    def test_wrap_with_warnings(self, mfp):
        result = mfp.wrap("content", critical_warnings=["field X missing"])
        assert "⚠" in result
        assert "field X missing" in result

    def test_wrap_with_refs(self, mfp):
        result = mfp.wrap("content", refs=["§k:abc§"])
        assert "§k:abc§" in result

    def test_dedup_and_wrap(self, mfp):
        mfp.dedup.dedup("hello world")
        result, was_dedup = mfp.dedup_and_wrap("hello world")
        assert was_dedup
        assert "§k:" in result
