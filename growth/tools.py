from __future__ import annotations

import json
import re
import sqlite3

from pydantic import BaseModel, ConfigDict, StrictStr, Field, field_validator

from mc.core import WORLD, digest, dumps, read_json
from .runtime import RESULTS, settings


class ToolQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    terms: list[StrictStr] = Field(max_length=8,description='Single keywords for one API-catalogue query, no synonym lists.')

    @field_validator('terms')
    @classmethod
    def single_keywords(cls,terms):
        if any(not re.fullmatch(r'[\w]{1,64}',term) for term in terms):
            raise ValueError('Each search term must be one short keyword')
        return terms

    @property
    def query(self):
        return ' '.join(dict.fromkeys(self.terms))


class Catalogue:
    """An experiment-specific FTS5 view of unchanged upstream API definitions."""
    def __init__(self):
        self.definitions={}
        for path in sorted((WORLD/'data/api_docs/standard').glob('*.json')):
            for name, definition in read_json(path).items():
                self.definitions[f'{path.stem}.{name}']=definition
        self.version=digest(self.definitions)
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE VIRTUAL TABLE tools USING fts5(identity UNINDEXED, name, description)')
        for identity, definition in self.definitions.items():
            self.db.execute('INSERT INTO tools VALUES (?,?,?)',
                (identity,identity.replace('_',' ').replace('.',' '),definition['description']))

    def search(self, query):
        terms=list(dict.fromkeys(re.findall(r'[\w]+',query.lower())))
        if not terms: return []
        expression=' OR '.join('"'+term+'"' for term in terms)
        hits=self.db.execute('SELECT identity,bm25(tools) FROM tools WHERE tools MATCH ? '
            'ORDER BY bm25(tools),identity LIMIT ?', (expression,settings().tool_search_limit)).fetchall()
        return [{'id':ident,'content':dumps(self.definitions[ident]),'rank':i+1,'fts_score':score,
                 'catalogue_version':self.version} for i,(ident,score) in enumerate(hits)]

    def identity(self, call):
        matches=[]
        for ident,d in self.definitions.items():
            pattern=re.sub(r'\{[^}]+\}',r'[^/]+',d['path'])
            if d['method'].lower()==call['method'].lower() and re.fullmatch(pattern,call['url']):
                matches.append(ident)
        return matches[0] if len(matches)==1 else None


def discovery_messages(instruction, observation, memories):
    return [{'role':'system','content':
        'Return JSON {"terms":["app","capability","object"]} for ONE search query. '
        'Choose only the next needed capability, using two to eight single keywords. '
        'Do not enumerate synonyms or alternative queries. Return an empty terms array if discovery is unnecessary. '
        'Search API names and descriptions. Do not solve the task '
        'or propose action arguments. Historical knowledge is advisory; current observations govern.'},
        {'role':'user','content':dumps({'task':instruction,'latest_action_observation':observation,
                                      'historical_memory':memories})}]
