"""
run_all_tests.py
~~~~~~~~~~~~~~~~
Bộ điều phối và báo cáo kiểm thử phân nhóm minh bạch cho HyperMedia Downloader Pro.

Phân nhóm 7 cấp độ độc lập, tách bạch tuyệt đối giữa Offline vs Live Network vs UI vs Frozen Process:
  1. Offline unit tests (Mock 100%, 0 Network, 0 External Process)
  2. Drama integration tests (Domain contracts, Routing, Access States & Mock Backend)
  3. Cleanup tests (Filesystem strict exact stem isolation, Zero false delete)
  4. Network tests (Gọi mạng thực tế: GoogleVideo CDN HTTP Range: bytes=0-1024, ByteDance Live Share & Catalog)
  5. GUI smoke tests (Thử nghiệm giao diện offscreen: Hongguo catalog, Kylin, NovelQuickApp, Douyin share, MiniApp catalog)
  6. Python runtime smoke (Kiểm tra QuickJS nhúng trên môi trường Python lọc sạch PATH)
  7. Frozen EXE smoke (Chạy file EXE thật từ tempdir, lọc sạch PATH, xác minh _MEI{pid})
"""

import os
import sys
import time
import unittest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def get_test_groups():
    from tests.test_drama_reproductions import TestDramaReproduction
    from tests.test_drama_integration import TestDramaIntegration
    from tests.test_hongguo_audit_and_access_contract import TestHongguoAuditAndAccessContract
    from tests.test_free_first_providers_contract import TestFreeFirstProvidersContract
    from tests.test_drama_network_guard import TestDramaNetworkGuard
    from tests.test_miniapp_provider_contract import TestMiniAppProviderContract
    from tests.test_miniapp_cookie_sync import TestMiniAppCookieSync
    from tests.test_miniapp_selection import TestMiniAppSelection
    from tests.test_miniapp_access_guard import TestMiniAppAccessGuard
    from tests.test_miniapp_download_queue import TestMiniAppDownloadQueue
    from tests.test_miniapp_contract import TestMiniAppContract
    from tests.test_miniapp_access_state import TestMiniAppAccessState
    from tests.test_miniapp_no_network_on_locked import TestMiniAppNoNetworkOnLocked
    from tests.test_miniapp_ux_and_paths import TestMiniAppUXAndPaths
    from tests.test_drama_pagination_and_expansion import TestDramaPaginationAndExpansion
    from tests.test_hongguo_kylin_and_catalog import TestHongguoKylinAndCatalog
    from tests.test_entitlement_and_vip_contract import TestEntitlementAndVIPContract
    from tests.test_responsive_ui_and_provider_priority import TestResponsiveUIAndProviderPriority
    from tests.test_commercial_ui_and_ca_bundle import TestCommercialUIAndCABundle
    from tests.test_catalog_provider_classification_and_race_guard import TestCatalogProviderClassificationAndRaceGuard
    from tests.test_four_interactive_concurrency_scenarios import TestFourInteractiveConcurrencyScenarios
    from tests.test_qthread_real_concurrency_lifecycle import TestQThreadRealConcurrencyLifecycle
    from tests.test_miniapp_session_lifecycle import TestMiniAppSessionLifecycle
    from tests.test_hongguo_queue_download import TestHongguoQueueDownload
    from tests.test_provider_resolver_routing import TestProviderResolverRouting
    from tests.test_episode_metadata_roundtrip import TestEpisodeMetadataRoundtrip
    from tests.test_drama_queue_download_contract import TestDramaQueueDownloadContract
    from tests.test_parallel_part_isolation import TestParallelPartIsolation
    from tests.test_youtube_clean_machine_smoke import (
        TestPythonCleanMachineRuntimeSmoke,
        TestYouTubeLiveNetworkRangeProbe,
    )
    from tests.test_live_hongguo_and_douyin_probe import TestLiveHongguoAndDouyinProbe
    from tests.test_gui_smoke_manual import TestGUISmokeManual
    from tests.test_exe_clean_machine_smoke import TestExeCleanMachineSmoke
    from qa_test_suite import (
        TestFilenameAndPrefix,
        TestDuplicateHandling,
        TestYouTubeRegression,
        TestBilibiliRegression,
        TestDouyinRegression,
        TestPartFileCleanupIsolation,
        TestCookieAutoSyncContract,
    )

    return [
        {
            "id": 1,
            "title": "Offline Unit Tests",
            "mode": "Offline Mock (100% Mock, 0 Network, 0 External Process)",
            "test_cases": [
                TestDramaReproduction,
                TestFilenameAndPrefix,
                TestDuplicateHandling,
                TestYouTubeRegression,
                TestBilibiliRegression,
                TestDouyinRegression,
                TestCookieAutoSyncContract,
            ],
        },
        {
            "id": 2,
            "title": "Drama & MiniApp Integration Tests",
            "mode": "Domain & Provider Mock (Access States, Routing, Spade Fixture, Free-First Providers, Network Guard, MiniApp)",
            "test_cases": [
                TestDramaIntegration,
                TestHongguoAuditAndAccessContract,
                TestFreeFirstProvidersContract,
                TestDramaNetworkGuard,
                TestMiniAppProviderContract,
                TestMiniAppCookieSync,
                TestMiniAppSelection,
                TestMiniAppAccessGuard,
                TestMiniAppDownloadQueue,
                TestMiniAppContract,
                TestMiniAppAccessState,
                TestMiniAppNoNetworkOnLocked,
                TestMiniAppUXAndPaths,
                TestDramaPaginationAndExpansion,
                TestHongguoKylinAndCatalog,
                TestEntitlementAndVIPContract,
                TestResponsiveUIAndProviderPriority,
                TestCommercialUIAndCABundle,
                TestCatalogProviderClassificationAndRaceGuard,
                TestFourInteractiveConcurrencyScenarios,
                TestQThreadRealConcurrencyLifecycle,
                TestMiniAppSessionLifecycle,
                TestHongguoQueueDownload,
                TestProviderResolverRouting,
                TestEpisodeMetadataRoundtrip,
                TestDramaQueueDownloadContract,
            ],
        },
        {
            "id": 3,
            "title": "Cleanup Tests",
            "mode": "Filesystem Isolation (Exact Stem, Zero False Delete)",
            "test_cases": [
                TestParallelPartIsolation,
                TestPartFileCleanupIsolation,
            ],
        },
        {
            "id": 4,
            "title": "Network Tests",
            "mode": "Live Network Probe (GoogleVideo CDN Range: bytes=0-1024, ByteDance Live Share & Catalog Probes)",
            "test_cases": [
                TestYouTubeLiveNetworkRangeProbe,
                TestLiveHongguoAndDouyinProbe,
            ],
        },
        {
            "id": 5,
            "title": "GUI Smoke Tests",
            "mode": "Offscreen PySide6 UI (Hongguo Catalog, Kylin, NovelQuickApp, Douyin Share, MiniApp Catalog)",
            "test_cases": [
                TestGUISmokeManual,
            ],
        },
        {
            "id": 6,
            "title": "Python Runtime Smoke",
            "mode": "Python Clean-Machine Simulation (Clean PATH, QuickJS Embedded)",
            "test_cases": [
                TestPythonCleanMachineRuntimeSmoke,
            ],
        },
        {
            "id": 7,
            "title": "Frozen EXE Smoke",
            "mode": "Frozen Standalone Process (Tempdir CWD, Clean PATH, _MEI{pid})",
            "test_cases": [
                TestExeCleanMachineSmoke,
            ],
        },
    ]


def run_tests():
    loader = unittest.TestLoader()
    groups = get_test_groups()

    group_results = []
    skipped_records = []
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_skipped = 0
    grand_start = time.time()

    print("=" * 80)
    print("HYPERMEDIA DOWNLOADER PRO - BÁO CÁO KIỂM THỬ PHÂN NHÓM MINH BẠCH")
    print("=" * 80)

    for g in groups:
        suite = unittest.TestSuite()
        for tc in g["test_cases"]:
            suite.addTests(loader.loadTestsFromTestCase(tc))

        count = suite.countTestCases()
        print(f"\n>>> [{g['title']}] ({count} tests)")
        print(f"    Chế độ: {g['mode']}")
        print("-" * 80)

        runner = unittest.TextTestRunner(verbosity=1, stream=sys.stdout)
        start_t = time.time()
        res = runner.run(suite)
        elapsed = time.time() - start_t

        is_success = res.wasSuccessful()
        group_results.append({
            "id": g["id"],
            "title": g["title"],
            "mode": g["mode"],
            "run": res.testsRun,
            "passed": res.testsRun - len(res.failures) - len(res.errors) - len(res.skipped),
            "failed": len(res.failures),
            "errors": len(res.errors),
            "skipped": len(res.skipped),
            "elapsed": elapsed,
            "success": is_success,
        })

        total_passed += res.testsRun - len(res.failures) - len(res.errors) - len(res.skipped)
        total_failed += len(res.failures)
        total_errors += len(res.errors)
        total_skipped += len(res.skipped)
        for skipped_test, reason in res.skipped:
            skipped_records.append((g["id"], skipped_test.id(), reason))

    total_time = time.time() - grand_start

    # Bảng tổng kết
    print("\n" + "=" * 92)
    print("BẢNG TỔNG HỢP KẾT QUẢ KIỂM THỬ THEO TỪNG NHÓM ĐỘC LẬP")
    print("=" * 92)
    header_fmt = "{:<8} {:<28} {:<10} {:<10} {:<10} {:<28}"
    print(header_fmt.format("Nhóm", "Phân Loại Test", "Số Test", "Kết quả", "Thời gian", "Đặc điểm môi trường"))
    print("-" * 92)

    all_ok = True
    for gr in group_results:
        if not gr["success"]:
            status_str = "FAIL"
            all_ok = False
        elif gr["skipped"] > 0:
            status_str = f"PASS({gr['skipped']}S)"
        else:
            status_str = "PASS"
        time_str = f"{gr['elapsed']:.2f}s"
        if gr["id"] in (1, 2, 3):
            env_tag = "0 Network, Mock"
        elif gr["id"] == 4:
            env_tag = "Live CDN Request"
        elif gr["id"] == 5:
            env_tag = "Offscreen PySide6 UI"
        elif gr["id"] == 6:
            env_tag = "Clean PATH Python + QuickJS"
        else:
            env_tag = "Clean PATH Frozen EXE"
        print(header_fmt.format(f"Nhóm {gr['id']}", gr["title"][:26], f"{gr['run']} tests", status_str, time_str, env_tag))

    total_all = total_passed + total_failed + total_errors + total_skipped
    if not all_ok:
        overall_status = "CÓ TEST THẤT BẠI"
    elif total_skipped > 0:
        overall_status = f"THÀNH CÔNG ({total_passed}/{total_all} PASS, {total_skipped} SKIP có lý do)"
    else:
        overall_status = f"THÀNH CÔNG ({total_passed}/{total_all} PASS)"

    print("-" * 92)
    print(f"TỔNG CỘNG: {total_all} tests | "
          f"PASS: {total_passed} | FAIL: {total_failed} | ERROR: {total_errors} | SKIP: {total_skipped} | "
          f"Thời gian: {total_time:.2f}s")
    print(f"TRẠNG THÁI TOÀN BỘ: {overall_status}")
    if skipped_records:
        print("CHI TIẾT TEST BỊ SKIP:")
        for gid, tid, reason in skipped_records:
            print(f"  - [Nhóm {gid}] {tid}: {reason}")
    print("=" * 92 + "\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run_tests())
