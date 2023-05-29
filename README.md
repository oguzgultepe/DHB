# Notification Timing for a Proactive Virtual Dietary Advisor
This repo contains the source files for my bachelor's thesis. Here is the abstract:

We want to build a system that can accurately predict when a user is likely to eat. 
In order to accomplish this, we first build a chatbot that let's users log their eating patterns.
Next we integrate this chatbot into Telegram and share the access link with some volunteers in order to test it.
The chatbot collects a total of 150 entries in a duration of roughly 2 weeks.
Most of these entries are from 3 users.
We train separate models on the eating patterns of these 3 users
and use these models to predict when the user is going to eat again.
When we test the best performing models of each user on unseen data,
we get $R^2$ scores of $0.675$, $0.869$ and $0.895$.
