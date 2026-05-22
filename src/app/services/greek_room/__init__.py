# Greek-Room tool family.
#
# One module per tool. Each tool exposes a service class with the
# registry-ready surface (name, request_schema, response_schema,
# async execute) so future expansion into a tool registry/protocol
# does not require modifying existing tools.
#
# Current tools:
#   repeated_words.RepeatedWordsService — flags consecutive duplicate
#       words in a corpus of verses, distinguishing legitimate from
#       suspicious repetitions.
