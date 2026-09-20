# VKU-14 ReAct loop

`perk_watch.react.ReActRuntime` is a bounded direct-dispatch loop. A model selects
one of six Pydantic-typed tools, observes JSON data, and can ask for another
tool. Invalid model steps and tool arguments become observations and can be
retried; tool exceptions are also data. The loop renders the final sentence
from verified tool facts rather than trusting model arithmetic or status claims.

The evaluator callback is the only source for status, values, deadlines, and
evidence. `official_retriever` binds `OfficialClauseIndex.search` to the fixed
terms version and evaluated date. Community retrieval is optional and returns
`available: false` with an empty ideas list when absent.

A framework would add generic planning, memory, and tool registration. This
bounded flow needs none of those: direct dispatch keeps the authority boundary
and validation behavior visible.
