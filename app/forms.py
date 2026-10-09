"""Reading HTML forms.

The web framework refuses forms with more than 1,000 fields by default. Tagwerk's tick lists
are longer than that in a real library (1,196 ticked changes on the Changes page, a big record
pool drop in the inbox), so every form is read through here with a much higher limit.
"""

from fastapi import Request

# Each ticked change, track or file is one field. 100,000 covers any library.
MAX_FIELDS = 100_000


async def read_form(request: Request):
    return await request.form(max_fields=MAX_FIELDS)
