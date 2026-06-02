# -*- coding: utf-8 -*-
"""Session summary prompt definition."""

SUMMARIZE_PROMPT = """Based on this conversation's context, generate a short session title and summary.

Requirements:
- title: 3-8 words, summarizing the conversation topic
- summary: 1-2 sentences, summarizing what was discussed and the conclusions

Reply strictly in the following JSON format, do not add any other content:
{"title": "...", "summary": "..."}"""
