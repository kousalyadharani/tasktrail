import tempfile,unittest
from pathlib import Path
from tasktrail import submit,run_pipeline,connect,extract_tasks
class TaskTrailTests(unittest.TestCase):
 def test_extract_and_checkpoint_idempotency(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/"x.db"; rid=submit("From: a@b\nSubject: Demo\n\n- Review report due 2027-05-03\nPlease send the agenda",db); run_pipeline(rid,db); run_pipeline(rid,db)
   c=connect(db); rows=c.execute("select title,due_date from tasks where run_id=?",(rid,)).fetchall(); c.close(); self.assertEqual(len(rows),2); self.assertIn(("Review report due 2027-05-03","2027-05-03"),[(r["title"],r["due_date"]) for r in rows])
 def test_empty_non_action_line_ignored(self): self.assertEqual(extract_tasks("Hello there\n- Review the draft"),["Review the draft"])
if __name__=="__main__":unittest.main()
