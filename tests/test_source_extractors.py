"""Structured extractor fixtures, never live sources."""
import json
import unittest
import source_extractors as adapters

class SourceCase(unittest.TestCase):
 def test_rss_atom_jsonfeed_and_field_changes(self):
  rss='<rss><channel><title>Feed</title><item><guid>one</guid><title>A</title><link>https://example.org/a</link><pubDate>today</pubDate><description>First</description></item></channel></rss>'
  before=adapters.extract(rss,'application/rss+xml')
  after=adapters.extract(rss.replace('First','Updated').replace('Feed','Navigation changed'),'application/rss+xml')
  self.assertEqual(before['kind'],'rss')
  self.assertEqual(adapters.changes(before,after)['updated'][0]['id'],'one')
  navigation=adapters.extract(rss.replace('Feed','Navigation changed'),'application/rss+xml')
  self.assertEqual(adapters.comparable(before),adapters.comparable(navigation))
  atom='<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id><title>A</title><updated>today</updated><link href="https://example.org/a"/><summary>First</summary></entry></feed>'
  self.assertEqual(adapters.extract(atom,'application/atom+xml')['items'][0]['url'],'https://example.org/a')
  feed={'version':'https://jsonfeed.org/version/1.1','items':[{'id':'one','title':'A','content_html':'<p>First</p><script>ignore</script>'}]}
  self.assertEqual(adapters.extract(json.dumps(feed),'application/feed+json')['items'][0]['summary'],'First')
  self.assertIsNone(adapters.extract('{"plain":true}','application/json'))
 def test_malformed_entities_duplicate_ids_and_limits_fail_closed(self):
  for text in ['<rss>','<!DOCTYPE rss [<!ENTITY x "boom">]><rss/>','<rss><channel><item><guid>x</guid></item><item><guid>x</guid></item></channel></rss>']:
   with self.assertRaises(ValueError):adapters.extract(text,'application/rss+xml')
  with self.assertRaises(ValueError):adapters.normalize([{'id':str(i)} for i in range(121)],'rss')
  with self.assertRaises(ValueError):adapters.extract('{broken','application/json')
 def test_structured_hash_is_bound_to_actual_fields(self):
  original=adapters.normalize([{'id':'one','title':'A','summary':'a\nb'}],'rss')
  self.assertEqual(original['items'][0]['summary'],'a b')
  changed=adapters.normalize([{'id':'one','title':'A','summary':'a c'}],'rss')
  self.assertNotEqual(original['items'][0]['version'],changed['items'][0]['version'])
