"""Room planning: one sentence describing a room, real products within budget.

A customer writes something like "a living room with a sofa, two chairs and a
table, under 40,000". The model reads the sentence into slots, one per kind of
furniture with a quantity. Deterministic code then picks one real catalogue
product per slot so the whole room fits the budget, and says so honestly when
it cannot.

The model never chooses a product. It only turns the sentence into slots, the
same division of labour as search: language to the model, the marketplace to
code. A separate endpoint renders an AI preview image of the chosen products,
and that image is labelled as a preview everywhere it appears, because it is
the one thing in this package that is not a catalogue fact.
"""
