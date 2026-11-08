import unittest
from afternoon_tea.routine_enrichment import enrich_plan

class PlanEvidenceTests(unittest.TestCase):
    def test_plan_source_and_actual_check_time_override_old_shop_listing(self):
        shop={'source_url':'https://old.example.com/plan','checked_at':'2026-11-07T10:00:00+09:00'}
        plan={'plan_name':'苺アフタヌーンティー（平日）','menu':'苺タルト、スコーン',
              'source_url':'https://official.example.com/tea','checked_at':'2026-11-08T11:00:00+09:00'}
        result=enrich_plan(plan,shop)
        for evidence in result['structured_evidence'].values():
            self.assertEqual(evidence['url'],plan['source_url'])
            self.assertEqual(evidence['checked_at'],plan['checked_at'])
        self.assertEqual(shop['checked_at'],'2026-11-07T10:00:00+09:00')

    def test_unknown_plan_check_time_does_not_borrow_old_source_date(self):
        result=enrich_plan({'plan_name':'苺AT','source_url':'https://new.example.com/tea'},
                           {'source_url':'https://old.example.com/','checked_at':'old'})
        self.assertIsNone(result['structured_evidence']['sweets']['checked_at'])

    def test_legacy_plan_without_source_keeps_documented_shop_fallback(self):
        result=enrich_plan({'plan_name':'苺AT'}, {'source_url':'https://old.example.com/','checked_at':'old'})
        self.assertEqual(result['structured_evidence']['sweets']['url'],'https://old.example.com/')
        self.assertEqual(result['structured_evidence']['sweets']['checked_at'],'old')
