"""准入控制单测：全局并发信号量 + 单账号每分钟限流。"""
from __future__ import annotations

import asyncio

from backend.services import admission


def test_admission_rpm_blocks_repeated_sender():
    adm = admission.ChatAdmission(max_active=4, rpm=2, queue_timeout=5)

    async def main():
        t1 = await adm.enter("user-a")
        t2 = await adm.enter("user-a")
        try:
            await adm.enter("user-a")  # 同一账号第 3 条，限流窗口内
            assert False, "应当触发每分钟限流"
        except admission.AdmissionRejected as e:
            assert e.status == 429
            assert "频繁" in e.message
        await t1.release()
        await t2.release()

    asyncio.run(main())


def test_admission_queue_times_out_when_full():
    adm = admission.ChatAdmission(max_active=1, rpm=20, queue_timeout=0.3)

    async def main():
        t1 = await adm.enter("user-a")
        try:
            # 只剩 1 个名额且被占用，排队 0.3 秒后拒绝
            await adm.enter("user-b")
            assert False, "应当排队超时被拒绝"
        except admission.AdmissionRejected as e:
            assert e.status == 429
        finally:
            await t1.release()
        snap = adm.snapshot()
        assert snap["active"] == 0 and snap["waiting"] == 0

    asyncio.run(main())


def test_admission_release_frees_slot():
    adm = admission.ChatAdmission(max_active=1, rpm=20, queue_timeout=5)

    async def main():
        t1 = await adm.enter("user-a")
        await t1.release()
        t2 = await adm.enter("user-b")
        await t2.release()
        assert adm.snapshot()["active"] == 0

    asyncio.run(main())
