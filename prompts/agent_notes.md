<!-- purpose: agent mode in-loop messages: a refused tool request, the last tool round, the repair round; each section after a "## " line | last moved: (new, no eval yet) -->
## limit
Limit reached: no more tool calls for this question. Answer now from the passages already shown, or return not_found.

## last_round
Those were your last tool results for this question. Answer now from the passages shown, or return not_found.

## repair
None of the quotes in your answer could be found in the passage it names:
{failed}

A quote must be copied word for word from the chunk it cites. Answer again with exact quotes (you can reread a passage with get_chunk), or return not_found.
