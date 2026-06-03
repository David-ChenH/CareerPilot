# Product Spec

## Goal

Build a local-first AI job search copilot that helps users discover, evaluate, track, and prepare for jobs based on their private background and preferences.

## User profile

The initial target user is a software engineer who wants a structured, profile-aware workflow for job discovery, application tracking, resume tailoring, and interview preparation.

## MVP scope

The first version supports pasted job descriptions. Web search and browser automation come later after the core judgment loop is reliable.

The app also supports fetching a single job link when the page exposes readable HTML. Some job boards require browser automation or manual paste because they render content with JavaScript or block automated requests.

## Core workflows

1. Profile memory
   - Store background, skills, preferences, target roles, and avoid criteria.
   - Support structured updates later.

2. Job analysis
   - Extract title, company, location, seniority, skills, and requirements.
   - Preserve source URLs when users analyze from job links.
   - Score fit against the profile.
   - Explain matches, gaps, and application priority.

3. Application tracking
   - Persist discovered jobs.
   - Track status from discovered to applied/interviewing/rejected/offer.
   - Open original job links later.
   - Delete saved jobs.
   - Avoid duplicate records when possible.

4. Resume and prep suggestions
   - Suggest truthful resume emphasis.
   - Suggest skills/resources to learn.
   - Generate prep topics based on gaps.

## Non-goals for MVP

- Fully autonomous applications.
- Scraping sites that disallow automated access.
- Inventing resume experience.
- Cloud deployment.
