"""Small structured-output adaptation of the existing measured Vertex client."""
from mc.provider import Vertex as MeasuredVertex
from .tools import ToolQuery


FACTS_SCHEMA={'type':'object','properties':{'facts':{'type':'array','items':{'type':'string'}}},
              'required':['facts'],'additionalProperties':False}


def response_schema(messages,purpose):
    if purpose=='tool-search-query':return ToolQuery.model_json_schema()
    if purpose=='mem0-learning' and any(
        m['role']=='system' and 'SOURCE-BOUND FACT EXTRACTION' in m['content'] for m in messages):
        return FACTS_SCHEMA
    return None


class Vertex(MeasuredVertex):
    def __init__(self,ledger):
        super().__init__(ledger)
        dispatch=self.sdk.models.generate_content
        def structured_dispatch(*args,**kwargs):
            schema=self.scope.get('response_json_schema')
            if schema:
                kwargs['config']=kwargs['config'].model_copy(update={'response_json_schema':schema})
            return dispatch(*args,**kwargs)
        self.sdk.models.generate_content=structured_dispatch

    def generate(self,messages,*,json_mode=False,purpose='generation'):
        schema=response_schema(messages,purpose)
        # Exact effective schema is retained in every request's measured scope.
        with self.scoped(response_json_schema=schema):
            return super().generate(messages,json_mode=json_mode,purpose=purpose)
