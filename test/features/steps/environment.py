from steps.zotero import Zotero
from behave.contrib.scenario_autoretry import patch_scenario_with_autoretry
from behave.tag_matcher import ActiveTagMatcher, setup_active_tag_values
import re
from contextlib import contextmanager
import urllib.request
from munch import *
import os
import steps.utils as utils
import sys
import json

active_tag_value_provider = {
  'client': 'zotero',
  'slow': 'false',
}
active_tag_matcher = ActiveTagMatcher(active_tag_value_provider)

def before_feature(context, feature):
  if lme:= context.config.userdata.get('log_memory_every'):
    context.zotero.execute('Zotero.BetterBibTeX.TestSupport.startTimedMemoryLog(msecs)', msecs=int(lme))
  if active_tag_matcher.should_exclude_with(feature.tags):
    feature.skip(reason="DISABLED ACTIVE-TAG")

  for scenario in feature.walk_scenarios():
    retries = 0
    for tag in scenario.effective_tags:
      if tag.startswith('retries='):
        retries = int(tag.split('=')[1])

    if retries > 0:
      patch_scenario_with_autoretry(scenario, max_attempts=retries + 1)

class TestBin:
  def __init__(self):
    self.bin = None
    self.test = None

  def load(self, context):
    if not 'bin' in context.config.userdata:
      return

    self.bin = int(context.config.userdata['bin'])

    assert 'bins' in context.config.userdata

    self.tests = {}

    with open(context.config.userdata['bins']) as f:
      self.tests = {
        test: i
        for i, _bin in enumerate(json.load(f))
        for test in _bin
      }

  def test_in(self, test):
    return self.tests.get(re.sub(r' -- @[0-9]+\.[0-9]+ ', '', test), 0)
TestBin = TestBin()

def before_all(context):
  TestBin.load(context)
  context.memory = Munch(total=None, increase=None)
  context.zotero = Zotero(context.config.userdata)
  setup_active_tag_values(active_tag_value_provider, context.config.userdata)
  # test whether the existing references, if any, have gotten a cite key
  context.zotero.export_library(translator = 'Better BibTeX')

def before_scenario(context, scenario):
  if active_tag_matcher.should_exclude_with(scenario.effective_tags):
    scenario.skip(f"DISABLED ACTIVE-TAG {str(active_tag_value_provider)}")
    return
  if TestBin.test_in(scenario.name) != TestBin.bin:
    scenario.skip(f'TESTED IN BIN {TestBin.test_in(scenario.name)}')
    return
  if 'test' in context.config.userdata and not any(test in scenario.name.lower() for test in context.config.userdata['test'].lower().split(',')):
    scenario.skip(f"ONLY TESTING SCENARIOS WITH {context.config.userdata['test']}")
    return

  context.zotero.reset(scenario.name)
  context.displayOptions = {}
  context.selected = []
  context.imported = None
  context.picked = []

  context.timeout = 60
  # jurism is just generally slower
  if context.config.userdata.get('client') == 'jurism': context.timeout *= 3
  for tag in scenario.effective_tags:
    if tag == 'use.with_slow=true':
      context.timeout = max(context.timeout, 300)
    elif tag.startswith('timeout='):
      context.timeout = max(context.timeout, int(tag.split('=')[1]))
  context.zotero.config.timeout = context.timeout

def after_scenario(context, scenario):
  if context.memory.increase or context.memory.total:
    memory = Munch.fromDict(context.zotero.execute('return Zotero.BetterBibTeX.TestSupport.memoryState("behave cap")'))
    if context.memory.increase and memory.delta > context.memory.increase:
      raise AssertionError(f'Memory increase cap of {context.memory.increase}MB exceeded by {memory.delta - context.memory.increase}MB')
    if context.memory.total and memory.resident > context.memory.total:
      raise AssertionError(f'Total memory cap of {context.memory.total}MB exceeded by {memory.resident - context.memory.total}MB')
