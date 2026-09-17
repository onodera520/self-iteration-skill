"""Structured behavior fixtures, not automated visual recognition or real-image QA."""
import copy
import unittest
import test_previs as fixtures
import test_imported_review as imported_fixtures
import previs as core
import planner
import storyboard as boards


class AssetEvidenceTests(fixtures.Base):
    setUp = imported_fixtures.ImportedReviewTests.setUp
    png = imported_fixtures.ImportedReviewTests.png
    select_mapping = imported_fixtures.ImportedReviewTests.select_mapping
    mapping = imported_fixtures.ImportedReviewTests.mapping
    review_data = imported_fixtures.ImportedReviewTests.review_data
    finish = imported_fixtures.ImportedReviewTests.finish

    def sample(self, verdict='PASS'):
        self.mapping()
        r = self.review_data({'S02': verdict}, middle_derivable=False)
        c = next(c for c in r['asset_comparisons'] if c['shot_id']=='S02' and c['aspect']=='wardrobe')
        e = next(e for e in r['evidence'] if e['shot_id']=='S02') if verdict!='uncertain' else None
        c['condition_factors']=['rain', 'night lighting', 'wet reflections']
        if e:
            e.update(visible_facts=['notched lapel visible', 'white crew-neck inner layer', 'wet reflective surface'],
                     interpretation='Dark gloss is consistent with rain and lighting; lapel and inner layer match')
        c['stable_matches']=['notched lapel', 'white crew-neck inner layer'] if e else []
        if verdict=='FAIL':
            r['shot_reviews'][1]['checks'].update(identity='FAIL',props='PASS')
            c.update(decision='FAIL',story_requirement='Script requires suit as disguise recognition clue',story_impact='Changed jacket breaks the disguise recognition',stable_matches=[],stable_conflicts=[dict(feature='garment fasteners and collar',
                expected='notched lapel and white crew-neck layer', observed='asymmetric biker zipper, stand collar, closed dark inner layer',
                environment_exclusion='Rain can change gloss but cannot replace lapels with a zipper and stand collar')])
            e.update(visible_facts=['asymmetric zipper visible', 'stand collar', 'closed dark inner layer'],
                     interpretation='Clear structural conflict with suit asset')
            r['issues'][0].update(asset_ids=[c['asset_id']],asset_comparison_ids=[c['id']],problem='Structural wardrobe conflict')
        return r,c

    def test_rain_darkened_suit_passes_and_no_regeneration(self):
        r,c=self.sample()
        self.assertEqual(core.record_review(self.p,self.path,r),'PASS')
        self.assertEqual(planner.post_review_plan(self.p,self.path,{})['decisions'][1]['status'],'anchor_reviewed')

    def test_ordinary_appearance_deviations_and_distant_face_pass_without_comparisons(self):
        for facts in (['face differs, same actor role and action relationship recognizable'],
                      ['biker jacket replaces suit; no disguise or wardrobe plot cue'],
                      ['distant two people walking together; face and collar too small to see']):
            with self.subTest(facts=facts):
                r,c=self.sample()
                r['asset_comparisons']=[]
                for row in r['shot_reviews']:
                    row.pop('identity_scope',None)
                    row['identity_reason']='Actor and action relationship recognizable; appearance differences have no story impact'
                r['evidence'][1].update(visible_facts=facts,interpretation='Required story relationship remains clear')
                self.assertEqual(core.record_review(self.p,self.path,r),'PASS')

    def test_character_failure_or_uncertainty_requires_story_requirement_and_impact(self):
        for verdict in ('FAIL','uncertain'):
            r,c=self.sample('FAIL') if verdict=='FAIL' else (None,None)
            if verdict=='uncertain':
                self.mapping({'S02':'uncertain'})
                r=self.review_data()
                c=next(x for x in r['asset_comparisons'] if x['shot_id']=='S02')
            for field in ('story_requirement','story_impact'):
                bad=copy.deepcopy(r)
                next(x for x in bad['asset_comparisons'] if x['id']==c['id']).pop(field)
                with self.subTest(verdict=verdict,field=field),self.assertRaisesRegex(ValueError,field):
                    core.record_review(self.p,self.path,bad)

    def test_wrong_action_actor_fails_with_local_story_evidence(self):
        r,c=self.sample('FAIL')
        c.update(story_requirement='Girl must keep the key until the handoff',story_impact='Boy acts as key holder before handoff',
                 stable_conflicts=[dict(feature='acting character',expected='girl holding key',observed='boy holding key',
                                        environment_exclusion='Lighting cannot change who performs the action')])
        self.assertEqual(core.record_review(self.p,self.path,r),'FAIL')

    def test_identity_reason_and_fail_comparison_cannot_be_omitted(self):
        r,c=self.sample();r['shot_reviews'][1].pop('identity_reason')
        with self.assertRaisesRegex(ValueError,'identity_reason'):core.record_review(self.p,self.path,r)
        r,c=self.sample('FAIL');r['asset_comparisons']=[]
        with self.assertRaisesRegex(ValueError,'identity check contradicts'):core.record_review(self.p,self.path,r)

    def test_biker_breaking_required_disguise_fails_only_this_shot(self):
        r,c=self.sample('FAIL')
        self.assertEqual(core.record_review(self.p,self.path,r),'FAIL')
        self.assertEqual([x['status'] for x in planner.post_review_plan(self.p,self.path,{})['decisions']],
                         ['anchor_reviewed','mismatch','anchor_reviewed'])

    def test_dark_silhouette_with_required_identity_clue_needs_evidence(self):
        self.mapping({'S02':'uncertain'})
        r=self.review_data()
        for c in r['asset_comparisons']:
            if c['shot_id']=='S02':
                c.update(unobservable_features=['necessary collar/face structure hidden in dark silhouette'],
                         followup='Rescan same-shot front or side frames with a visible collar and face')
        self.assertEqual(core.record_review(self.p,self.path,r),'uncertain')
        self.assertEqual(planner.post_review_plan(self.p,self.path,{})['decisions'][1]['status'],'pending')
        self.assertFalse(self.p.get('tasks'))

    def test_fail_without_structural_conflict_rejected(self):
        r,c=self.sample('FAIL');c['stable_conflicts']=[]
        with self.assertRaisesRegex(ValueError,'stable_conflicts'):core.record_review(self.p,self.path,r)

    def test_multi_shot_issue_cannot_spread_local_fail(self):
        r,c=self.sample('FAIL')
        r['issues'][0]['shot_ids'].append('S01')
        r['shot_reviews'][0].update(verdict='FAIL')
        r['shot_reviews'][0]['checks']['key_state']='FAIL'
        r['reference_assessments'][0]['decision']='pending'
        with self.assertRaisesRegex(ValueError,'every shot'):core.record_review(self.p,self.path,r)

    def test_bad_asset_hash_time_or_borrowed_frame_rejected(self):
        r,c=self.sample()
        for field,value in [('asset_sha256','wrong'),('asset_id','unassigned')]:
            bad=copy.deepcopy(r);next(x for x in bad['asset_comparisons'] if x['id']==c['id'])[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):core.record_review(self.p,self.path,bad)
        for field,value in [('time',99),('sha256','wrong'),('path',r['evidence'][0]['path'])]:
            bad=copy.deepcopy(r);next(x for x in bad['asset_comparisons'] if x['id']==c['id'])['evidence_refs'][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'same-shot'):core.record_review(self.p,self.path,bad)

    def test_verdict_conflict_and_laundering_to_other_check_rejected(self):
        r,c=self.sample('FAIL')
        r['shot_reviews'][1]['checks'].update(identity='PASS',continuity='FAIL')
        with self.assertRaisesRegex(ValueError,'identity check contradicts'):core.record_review(self.p,self.path,r)

    def test_old_observation_cannot_be_promoted(self):
        r,c=self.sample();r['evidence'][1].pop('visible_facts')
        with self.assertRaisesRegex(ValueError,'visible_facts'):core.record_review(self.p,self.path,r)

    def test_pass_needs_positive_structure_and_no_conflict(self):
        r,c=self.sample();c['stable_matches']=[]
        with self.assertRaisesRegex(ValueError,'stable matches'):core.record_review(self.p,self.path,r)

    def test_wardrobe_does_not_pass_unseen_required_face(self):
        r,c=self.sample()
        face=next(x for x in r['asset_comparisons'] if x['shot_id']=='S02' and x['aspect']=='appearance')
        face.update(decision='uncertain',story_impact='Script requires recognizing the disguise wearer',stable_matches=[],unobservable_features=['required facial outline'],followup='Find clear same-shot face')
        with self.assertRaisesRegex(ValueError,'identity check contradicts'):core.record_review(self.p,self.path,r)

    def test_hand_closeup_can_exclude_irrelevant_face(self):
        r,c=self.sample()
        for s in r['shot_reviews'][1]['identity_scope']:
            if s['aspect']=='appearance':s.update(required=False,reason='Script requires only sleeve/hand; face is outside this closeup')
        r['asset_comparisons']=[x for x in r['asset_comparisons'] if not(x['shot_id']=='S02' and x['aspect']=='appearance')]
        self.assertEqual(core.record_review(self.p,self.path,r),'PASS')

    def test_uncertain_checks_and_followup_required(self):
        self.mapping({'S02':'uncertain'});r=self.review_data()
        for mutate in ('checks','followup','comparison_followup'):
            bad=copy.deepcopy(r)
            if mutate=='comparison_followup':
                next(c for c in bad['asset_comparisons'] if c['shot_id']=='S02')['followup']=''
            else:bad['shot_reviews'][1].pop(mutate)
            with self.subTest(field=mutate),self.assertRaises(ValueError):core.record_review(self.p,self.path,bad)

    def test_neighbor_interpretation_cannot_supply_local_structure(self):
        r,c=self.sample();c.update(basis_shot_ids=['S01'],evidence_refs=[])
        with self.assertRaisesRegex(ValueError,'local timed evidence'):core.record_review(self.p,self.path,r)

    def test_neighbor_cannot_supply_borrowed_fail(self):
        r,c=self.sample('FAIL')
        other=next(x for x in r['asset_comparisons'] if x['shot_id']=='S01' and x['asset_id']==c['asset_id'] and x['aspect']==c['aspect'])
        other['basis_shot_ids']=['S02']
        with self.assertRaisesRegex(ValueError,'borrowed FAIL'):core.record_review(self.p,self.path,r)

    def test_missing_asset_cannot_pass_even_with_current_context(self):
        self.mapping()
        aid=self.p['shots'][0]['asset_ids'][0]
        asset=next(a for a in self.p['assets'] if a['id']==aid)
        core.resolve(self.path,asset['path']).unlink()
        # Re-register source/mapping after change so the asset gate, not an older fingerprint, is exercised.
        self.mapping(revision=2);r=self.review_data(middle_derivable=False)
        with self.assertRaisesRegex(ValueError,'current asset'):core.record_review(self.p,self.path,r)

    def test_versions_invalidate_review_and_dependent_plan_but_not_frames(self):
        r,c=self.sample();self.finish(r)
        current=core.review_current(self.p,self.path,'G01')
        self.assertEqual((current['review_schema'],current['reference_policy_version']),(4,3))
        for field,old in [('review_schema',3),('reference_policy_version',2)]:
            current[field]=old
            self.assertIsNone(core.review_current(self.p,self.path,'G01'))
            self.assertIsNone(planner.current_aggregation(self.p,self.path))
            self.assertIsNotNone(boards.current_mapping(self.p,self.path,'G01'))
            current[field]=4 if field=='review_schema' else 3

    def test_replacement_asset_invalidates_review_and_plan(self):
        r,c=self.sample();self.finish(r)
        asset=next(a for a in self.p['assets'] if a['id']==c['asset_id'])
        core.resolve(self.path,asset['path']).write_bytes(b'replaced asset')
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        self.assertIsNone(planner.current_aggregation(self.p,self.path))


if __name__=='__main__': unittest.main()
