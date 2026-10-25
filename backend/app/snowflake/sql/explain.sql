SELECT AI_COMPLETE(
    model => ?, prompt => ?,
    model_parameters => {'temperature': 0, 'max_tokens': 256},
    response_format => TYPE OBJECT(fact_ids ARRAY(VARCHAR)),
    show_details => FALSE
)
