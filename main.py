### LOAD LIBRARIES #############################################################
import os # Interactions with OS (e.g. accessing files)
import random # Generating random numbers
import re # Regular Expressions
from wcwidth import wcwidth # To find widths of extended Unicode/emoji characters
import datetime # To format datetimes

import discord # Communicate with the Discord API
from discord.ext import commands
from discord.ui import Select, View, Modal, TextInput # For nice UI on user input
from dotenv import load_dotenv
from asyncio import TimeoutError # To implement timeouts on user interactions

load_dotenv() # Load environment variables related to the Discord API (from .env)
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')

import psycopg2 # Interactions with the PostgreSQL server
import psycopg2.extras
from psycopg2.extras import RealDictCursor # To read DB queries as dictionaries
from config import load_config

### LOADING THE BOT ############################################################

intents=discord.Intents.default()
intents.message_content = True
intents.reactions = True # Ensure that the bot can receive reactions
intents.messages = True
intents.members = True # To fetch guild members
bot = commands.Bot(command_prefix='!',intents=intents)

### HELPER FUNCTIONS ###########################################################

# Generate a random string using easily identifiable characters:
def generate_random_string(length=8):
    # Omit I, 1, 0, O.
    characterbank = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    return ''.join(random.choice(characterbank) for _ in range(length))

# Calculate string width, using wcwidth() for width of nonstandard characters:
def calculate_width(text):
    return round(sum(wcwidth(char) if wcwidth(char) != 2 else 2.2 for char in text))

# Pad a string to a given width using whitespace:
def pad_to_width(text, width):
    padding_needed = width - calculate_width(text)
    return text + ' ' * padding_needed

### BOT TRIGGER EVENTS #########################################################

# On-Load Script:
@bot.event
async def on_ready():
    for guild in bot.guilds:
        if guild.name == GUILD:

            print(
                f'{bot.user} is connected to the following guild:\n'
                f' - {guild.name}; guild.id = {guild.id}'
                )

            members = '\n - '.join([member.name for member in guild.members])
            print(f'Guild Members:\n - {members}')
            print(guild.id)

### PREDICATES FOR COMMAND RESTRICTION  ########################################

def is_dm():
    async def is_dm_predicate(ctx):
        return isinstance(ctx.channel, discord.DMChannel)
    return commands.check(is_dm_predicate)

def is_dm_or_approved_role():
    async def is_dm_or_approved_role_predicate(ctx):
        # Allow within DMs:
        if isinstance(ctx.channel, discord.DMChannel):
            return True
        # And allow within guild channels if the user has the 'Hunt Organizer' role:
        if isinstance(ctx.author, discord.Member):
            role = discord.utils.get(ctx.author.roles, name='Hunt Organizer')
            return role is not None
        return False
    return commands.check(is_dm_or_approved_role_predicate)

### !TEAM ######################################################################

# Main !team command group:
@bot.group(name='team', help='Commands to create/join/leave/delete a team. Enter !team for info.')
@is_dm()
async def team_action(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('The `!team` command facilitates various team management actions: \n'
        '- `!team create`, to register a new team \n'
        '- `!team join`, to join an existing team (using a password issued during team creation) \n'
        '- `!team leave`, to leave a team you\'ve joined (but not created)\n'
        '- `!team delete`, to delete a team you\'ve created')

# Team Creation Subcommand:
@team_action.command(name='create')
async def team_create_function(ctx):
    #Check if the user is currently assigned to a team. If so, abort.
    user_id = str(ctx.author.id)
    user_name = ctx.author.name

    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            sql = """SELECT * FROM solvers JOIN teams ON solvers.team_id = teams.team_id
                WHERE discord_id = %s"""
            data = (user_id,)
            cur.execute(sql,data)
            row = cur.fetchone()

            if row is not None:
                team_name = row['team_name']
                if row['is_captain']:
                    await ctx.send(f'You are currently registered to the team "{team_name}".\n'
                    'Use `!team delete` to delete that team before creating a new team.')
                else:
                    await ctx.send(f'You are currently registered to the team "{team_name}".\n'
                    'Use `!team leave` to leave that team before creating a new team.')
                return

    # Otherwise, begin with the dialogue for team creation:
    await ctx.send('Please enter the name of your team (max. 30 characters):')

    def check(m): # Check that the reply comes from the same user/channel.
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Display a confirmation message and await response for 60 seconds:
        msg = await bot.wait_for('message', timeout=60.0, check=check)
        team_name = msg.content
        if len(team_name) > 30:
            # TODO: Improve handling of string length for emoji/unicode characters.
            team_name_len = len(team_name)
            await ctx.send(f'Proposed team name is too long ({team_name_len} characters).\n'
                'Please try again using the `!team create` command.')
            return
        confirmation_msg = await ctx.send(f'Team name "{team_name}" has been set. Is this correct?')

        # Add emoji reacts to the message to speed up confirmation.
        green_check = '✅'
        red_x = '❌'
        await confirmation_msg.add_reaction(green_check)
        await confirmation_msg.add_reaction(red_x)

        def reaction_check(reaction, user):
            return (user == ctx.author and str(reaction.emoji) in [green_check, red_x]
                    and reaction.message.id == confirmation_msg.id)

        try:
            # If confirmed, issue a team token and update the database:
            # TODO: Ensure that team tokens are unique.
            reaction, user = await bot.wait_for('reaction_add', timeout=15.0, check=reaction_check)
            if str(reaction.emoji) == green_check:
                token = generate_random_string()
                # Connect to the DB
                config = load_config()
                with psycopg2.connect(**config) as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                        # Add team to database, and obtain the newly minted team_id:
                        sql = """INSERT INTO teams (team_name, team_token) VALUES (%s, %s)
                            RETURNING team_id;"""
                        data = (team_name, token)
                        cur.execute(sql, data)
                        team_id = cur.fetchone()['team_id']

                        # Add user to a list of registered solvers:
                        sql = """INSERT INTO solvers (discord_id, discord_name, team_id, is_captain)
                            VALUES (%s, %s, %s, %s);"""
                        data = (user_id, user_name, team_id, True)
                        cur.execute(sql, data)

                await ctx.send(f'Team creation successful. Other members may join using `!team join` and the following token: `{token}`.')

            elif str(reaction.emoji) == red_x:
                await ctx.send('Team creation terminated by user.')

        except TimeoutError: # If confirmation takes too long.
            await ctx.send('*Request has timed out. Please try again.*')

    except TimeoutError: # If team name entry takes too long.
        await ctx.send('*Request has timed out. Please try again.*')

# Team Joining Subcommand:
@team_action.command(name='join')
async def team_join_function(ctx):
    #Check if the user is currently assigned to a team. If so, abort.
    user_id = str(ctx.author.id)
    user_name = ctx.author.name

    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            sql = """SELECT * FROM solvers JOIN teams ON solvers.team_id = teams.team_id
                WHERE discord_id = %s"""
            data = (user_id,)
            cur.execute(sql,data)
            row = cur.fetchone()

            if row is not None:
                team_name = row['team_name']
                if row['is_captain']:
                    await ctx.send(f'You are currently registered to the team "{team_name}". '
                    'Use `!team delete` to delete that team before creating a new team.')
                else:
                    await ctx.send(f'You are currently registered to the team "{team_name}". '
                    'Use `!team leave` to leave that team before creating a new team.')
                return

    # Otherwise, begin with the dialogue for joining a team:
    await ctx.send('Please enter the password for the team you would like to join:')

    def check(m): # Check that the reply comes from the same user/channel.
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Display a confirmation message and await response for 60 seconds:
        msg = await bot.wait_for('message', timeout=60.0, check=check)
        team_token = msg.content

        # Connect to the DB:
        config = load_config()
        with psycopg2.connect(**config) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                # Check if a team with that token exists:
                sql = """SELECT * FROM teams WHERE team_token = %s"""
                data = (team_token,)
                cur.execute(sql, data)
                row = cur.fetchone()

                if row is None: # If the user input fails to match the token of any team:
                    await ctx.send(f'Failed to find a matching team. Please double-check the password and retry via `!team join`.')
                    return
                else:
                    team_id = row['team_id']
                    team_name = row['team_name']
                    # Add user to a list of registered solvers:
                    sql = """INSERT INTO solvers (discord_id, discord_name, team_id, is_captain)
                        VALUES (%s, %s, %s, FALSE)"""
                    data = (user_id, user_name, team_id)
                    cur.execute(sql, data)
                    await ctx.send(f'You have successfully joined the team "{team_name}".')

    except TimeoutError: # If team token entry takes too long.
        await ctx.send('*Request has timed out. Please try again.*')

# Team Leaving Subcommand:
@team_action.command(name='leave')
async def team_leave_function(ctx):
    user_id = str(ctx.author.id)
    user_name = ctx.author.name

    # Connect to the DB
    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Determine if the user is registered to a team:
            sql = """SELECT * FROM solvers JOIN teams ON solvers.team_id = teams.team_id
                WHERE discord_id = %s"""
            data = (user_id,)
            cur.execute(sql,data)
            row = cur.fetchone()

            if row is None: # If the user is not on a team, abort with adivce:
                await ctx.send('You are not yet registered to a team. '
                        'Create a new team with `!team create` '
                        'or join an existing team with `!team join`.')
            elif row['is_captain']: # If the user is a captain, abort with advice:
                await ctx.send('You cannot leave a team you have created. '
                        'To delete this team (removing **all members**), use `!team delete`.')
            else:
                # Otherwise, remove the user from the list of registered solvers:
                team_name = row['team_name']
                sql = """DELETE FROM solvers WHERE discord_id = %s;"""
                data = (user_id,)
                cur.execute(sql, data)
                await ctx.send(f'You have successfully left the team "{team_name}".')

# Team Deletion Subcommand:
@team_action.command(name='delete')
async def team_delete_function(ctx):
    user_id = str(ctx.author.id)
    user_name = ctx.author.name

    # Connect to the DB
    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Determine if the user is registered to a team as a captain:
            sql = """SELECT * FROM solvers JOIN teams ON solvers.team_id = teams.team_id
                WHERE discord_id = %s AND is_captain = TRUE"""
            data = (user_id,)
            cur.execute(sql,data)
            row = cur.fetchone()

            if row is None: # If the user is not a team captain, abort with advice:
                await ctx.send('*Team deletion is only available to users who have created teams.*')
            else:
                # Confirm the deletion request:
                team_name = row['team_name']
                confirmation_msg = await ctx.send('This action will delete the team '
                    f'"{team_name}" (removing all team members) and **cannot be undone**.\n'
                    'React with ✅ to confirm your choice or with ❌ to exit.')

                # Add emoji reacts to the message to speed up confirmation.
                green_check = '✅'
                red_x = '❌'
                await confirmation_msg.add_reaction(green_check)
                await confirmation_msg.add_reaction(red_x)

                def reaction_check(reaction, user):
                    return (user == ctx.author and str(reaction.emoji) in [green_check, red_x]
                            and reaction.message.id == confirmation_msg.id)

                try:
                    reaction, user = await bot.wait_for('reaction_add', timeout=15.0, check=reaction_check)
                    if str(reaction.emoji) == green_check:
                        # If confirmed, remove all teammates from the solvers list:
                        team_id = row['team_id']
                        sql = """DELETE FROM solvers WHERE team_id = %s"""
                        data = (team_id,)
                        cur.execute(sql, data)
                        # ... and mark the team as deleted:
                            # (This preserves the guesslog record better than a full scrub)
                        sql = """UPDATE teams SET is_deleted = TRUE
                            WHERE team_id = %s"""
                        data = (team_id,)
                        cur.execute(sql, data)
                        await ctx.send('You have successfully deleted this team. '
                            'Feel free to create a new team with `!team create` or '
                            'join an existing team with `!team join`.')

                    elif str(reaction.emoji) == red_x:
                        await ctx.send('Team deletion terminated by user.')
                except TimeoutError: # If confirmation takes too long.
                    await ctx.send('*Request has timed out. Please try again.*')

@team_action.error
async def team_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("The `!team` command is restricted to direct messages with the bot.")


### !LEADERBOARD ###############################################################

@bot.command(name='leaderboard', help='Display a leaderboard of registered teams.')
@is_dm_or_approved_role()
async def display_leaderboard(ctx):

    # Connect to the DB
    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Fetch the list of undeleted teams:
                # Order by hunt_solve_time, then score, then last_solve_time
            sql = """SELECT * FROM teams WHERE is_deleted = FALSE
                ORDER BY hunt_solve_time ASC, score DESC, last_solve_time ASC"""
            cur.execute(sql)

            # Make a matrix of somewhat-reformatted leaderboard data:
            team_place = 1
            is_hunt_won = False
            leaderboard_table = [["#", "Team Name", "Score", "Last Solve", "Hunt Finish"]]
            for row in cur:
                last_solve_datetime = row['last_solve_time'].strftime('%m-%d %H:%M:%S')
                if row['is_hunt_solved']:
                    is_hunt_won = True
                    display_team_name = '🔎' + row['team_name'] + '🔎'
                    hunt_solve_time = row['hunt_solve_time'].strftime('%m-%d %H:%M:%S')
                else:
                    display_team_name = row['team_name']
                    hunt_solve_time = ''
                team_data = [str(team_place), display_team_name, str(row['score']), last_solve_datetime, hunt_solve_time]
                leaderboard_table.append(team_data)
                team_place += 1

            # Only display "Hunt Finish" column if at least one team has finished:
            if is_hunt_won == False:
                leaderboard_table = [lb_row[:-1] for lb_row in leaderboard_table]

            # Compute maximal cell widths in each column:
            col_widths = [max(calculate_width(row[i]) for row in leaderboard_table) for i in range(len(leaderboard_table[0]))]

            # Generate the table in a code block environment:
            header_line = "-|-".join('-' * col_width for col_width in col_widths) + "\n"
            display_table = "```\n"
            for row in leaderboard_table:
                padded_row = [pad_to_width(cell, col_widths[i]) for i, cell in enumerate(row)]
                display_table += " | ".join(padded_row) + "\n"
                if row == leaderboard_table[0]:
                    display_table += header_line
            display_table += "```"

            await ctx.send(display_table)

@display_leaderboard.error
async def leaderboard_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("The `!leaderboard` command is restricted to use in direct messages to reduce spam.")
    else:
        raise error


### !PUZZLES DASHBOARD #########################################################

@bot.command(name='puzzles', help='Display a dashboard of available puzzles.')
@is_dm_or_approved_role()
async def display_puzzles(ctx):

    # Extract information about the user
    user_id = str(ctx.author.id) # As string to avoid DB integer overflows.

    # Connect to the DB
    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Determine if the user is registered to a team:
            sql = """SELECT * FROM solvers JOIN teams ON solvers.team_id = teams.team_id
                WHERE discord_id = %s"""
            data = (user_id,)
            cur.execute(sql, data)
            row = cur.fetchone()

            is_registered = (row is not None)
            if is_registered:
                team_id = row['team_id']
            else:
                team_id = None

            # In case this appears in a general channel, set team_id = None
            if isinstance(ctx.channel, discord.DMChannel) == False:
                team_id = None

            # Form a dictionary of id:answer pairs for puzzles solved by this team
                # Return id:None for unsolved puzzles
            sql = """SELECT puzzles.puzzle_id, guess
                    FROM puzzles LEFT JOIN guesslog ON puzzles.puzzle_id = guesslog.puzzle_id
                    AND team_id = %s AND guess_status = 'correct' ORDER BY puzzles.puzzle_id ASC"""
            data = (team_id,)
            cur.execute(sql, data)
            answer_dict = {row['puzzle_id'] : row['guess'] for row in cur}

            # Gather total solve/guess counts from the database:
            sql = """SELECT puzzles.puzzle_id AS p_id, puzzles.puzzle_name,
                    COUNT(CASE WHEN guess_status = 'correct' THEN 1 END) AS num_solves,
                    COUNT(CASE WHEN guess_status = 'incorrect' THEN 1 END) AS num_guesses
                    FROM puzzles LEFT JOIN guesslog ON guesslog.puzzle_id = puzzles.puzzle_id
                    GROUP BY puzzles.puzzle_id ORDER BY puzzles.puzzle_id ASC"""
            cur.execute(sql)

            # Make a matrix of somewhat-reformatted puzzle data:
            puzzles_table = [["#", "Puzzle Name", "# Solves", "# Guesses", "Answer"]]
            row_counter = 1
            is_an_answer_known = False
            for row in cur:
                puzzle_id = row['p_id']
                puzzle_name = row['puzzle_name']
                num_solves = str(row['num_solves'])
                num_guesses = str(row['num_guesses'])
                if answer_dict[puzzle_id] is None:
                    answer = ''
                else:
                    answer = answer_dict[puzzle_id]
                    is_an_answer_known = True

                puzzle_data = [str(row_counter), puzzle_name, num_solves, num_guesses, answer]
                puzzles_table.append(puzzle_data)
                row_counter += 1

            # Only display "Answer" column if at least one answer is known:
            if is_an_answer_known == False:
                puzzles_table = [lb_row[:-1] for lb_row in puzzles_table]

            # Compute maximal cell widths in each column:
            col_widths = [max(calculate_width(row[i]) for row in puzzles_table) for i in range(len(puzzles_table[0]))]

            # Generate the table in a code block environment:
            header_line = "-|-".join('-' * col_width for col_width in col_widths) + "\n"
            display_table = "```\n"
            for row in puzzles_table:
                padded_row = [pad_to_width(cell, col_widths[i]) for i, cell in enumerate(row)]
                display_table += " | ".join(padded_row) + "\n"
                if row == puzzles_table[0]:
                    display_table += header_line
            display_table += "```"

            await ctx.send(display_table)

@display_puzzles.error
async def puzzles_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("The `!puzzles` command is restricted to use in direct messages to reduce spam.")
    else:
        raise error


### GUESS PROCESSING BACKEND ###################################################

async def process_guess(ctx, puzzle_id, guess):

    # Extract information about the user
    user = ctx.author.name
    user_id = str(ctx.author.id) # As string to avoid DB integer overflows.

    # Connect to the DB
    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Determine if the user is registered to a team:
            # TODO: Redundant; this information could be passed from gather_guess()
            sql = """SELECT * FROM solvers JOIN teams ON solvers.team_id = teams.team_id
                WHERE discord_id = %s"""
            data = (user_id,)
            cur.execute(sql, data)
            row = cur.fetchone()

            # Restrict to registered users:
                # This only matters if a user leaves a team mid-hunt and interacts with an old interface.
            if row is None:
                await ctx.send('The `!guess` command is only available to registered solvers.\n'
                    'To register, create a team via `!team create` or join a team via `!team join`.')
                return

            # Otherwise, the user is on a team:
            team_id = row['team_id']
            num_guesses = row['num_guesses']
            team_score = row['score']

            # Sanitize the guess:
            sanitize = re.sub('[^A-Za-z0-9]+', '', guess)
            sanitize_lower = sanitize.lower()

            # Query the DB to determine the correct response to the guess:
            sql = """SELECT puzzles.puzzle_id AS p_id, puzzles.puzzle_name AS p_name,
                responses.response, is_answer, puzzle_points, is_final_puzzle,
                CASE WHEN puzzles.puzzle_name IS NULL THEN 'bad_puzzle'
                    WHEN responses.guess IS NULL THEN 'bad_guess'
                    ELSE 'success'
                END AS status
                FROM puzzles LEFT JOIN responses ON puzzles.puzzle_id = responses.puzzle_id
                AND responses.guess = %s
                WHERE puzzles.puzzle_id = %s;"""
            data = (sanitize_lower, puzzle_id)
            cur.execute(sql, data)
            guess_response_info = cur.fetchone()

            # Echo input as confirmation
            puzzle_name = guess_response_info['p_name']
            input_confirmation = f'{user} has guessed `{sanitize_lower}` on `{puzzle_name}`.'
            await ctx.send(input_confirmation)

            # Query the guesslog to determine if:
                # a. The puzzle has already been solved.
                # b. The guess is a duplicate guess.
            puzzle_id = guess_response_info['p_id']
            sql = """SELECT
                MAX(CASE WHEN guess_status = 'correct' THEN guess ELSE NULL END) AS solved_status,
                MAX(CASE WHEN guess = %s THEN 1 ELSE 0 END) AS duplicate_status
                FROM guesslog WHERE puzzle_id = %s AND team_id = %s;"""
            data = (sanitize_lower, puzzle_id, team_id)
            cur.execute(sql, data)
            prior_guess_info = cur.fetchone()
            solved_status = prior_guess_info['solved_status'] # None or [answer].
            duplicate_status = prior_guess_info['duplicate_status'] # None, 0, or 1.

            # Terminate if the puzzle has been solved:
            if solved_status != None:
                await ctx.send(f'Your team has already solved this puzzle with answer `{solved_status}`.')
                return

            # Otherwise, output a response to the guess:
            status = guess_response_info['status']
            if status == 'bad_guess':
                guess_status = 'incorrect'
                response = "Incorrect guess (no follow-up data available)."
            else:
                if guess_response_info['is_answer'] == True:
                    guess_status = 'correct'
                else:
                    guess_status = 'partial'
                response = guess_response_info['response']
            await ctx.send(response)

            # If the guess was a duplicate guess, terminate:
            if duplicate_status == 1:
                await ctx.send('*This was a duplicate guess and will be ignored.*')
                return

            # Otherwise, enter the guess into the guesslog:
            sql = """INSERT INTO guesslog (puzzle_id, team_id, guess, guess_status)
                    VALUES (%s, %s, %s, %s);"""
            data = (puzzle_id, team_id, sanitize_lower, guess_status)
            cur.execute(sql, data)

            # If the guess was incorrect, debit a guess from the team:
            if guess_status == 'incorrect':
                new_num_guesses = num_guesses - 1
                sql = """UPDATE teams SET num_guesses = %s WHERE team_id = %s"""
                data = (new_num_guesses, team_id)
                cur.execute(sql, data)

                if new_num_guesses != 1:
                    await ctx.send(f'*Your team has {new_num_guesses} guesses remaining.*')
                else:
                    await ctx.send(f'*Your team has {new_num_guesses} guess remaining.*')

            # If the guess was correct, update points and last_solve_time:
            if guess_status == 'correct':
                puzzle_points = guess_response_info['puzzle_points']
                sql = """UPDATE teams SET score = %s, last_solve_time = CURRENT_TIMESTAMP
                    WHERE team_id = %s"""
                data = (team_score + puzzle_points, team_id)
                cur.execute(sql, data)

                # And mark the team as "done" if this was the final puzzle:
                is_final_puzzle = guess_response_info['is_final_puzzle']
                if is_final_puzzle:
                    sql = """UPDATE teams SET is_hunt_solved = %s,
                        hunt_solve_time = CURRENT_TIMESTAMP WHERE team_id = %s"""
                    data = (is_final_puzzle, team_id)
                    cur.execute(sql, data)

### !GUESS  COMMAND ############################################################

# Define classes for dropdown menus and short response forms:
class DropdownView(View):
    def __init__(self, options, ctx):
        super().__init__()
        self.ctx = ctx
        self.add_item(SelectMenu(options, ctx))

class SelectMenu(Select):
    def __init__(self, options, ctx):
        self.ctx = ctx
        # Convert the dictionary 'options' to a list of SelectOption objects
        select_options = [discord.SelectOption(label=label, value=value) for label, value in options.items()]
        super().__init__(placeholder='Select a puzzle...', min_values=1, max_values=1, options=select_options)
    # Once a selection is made, display the short response form:
    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        await interaction.response.send_modal(ShortResponseModal(self.ctx, selected_value))

class ShortResponseModal(Modal):
    def __init__(self, ctx, selected_value):
        self.ctx = ctx
        self.selected_value = selected_value
        super().__init__(title="Enter a Guess")

        self.response = TextInput(label="Enter a Guess", placeholder="Type your guess here...", max_length=100)
        self.add_item(self.response)
    # Once a guess is entered, process that guess:
    async def on_submit(self, interaction: discord.Interaction):
        user_response = self.response.value
        await interaction.response.defer(ephemeral=True)  # Acknowledge the interaction without sending a message
        await process_guess(self.ctx, self.selected_value, user_response)

@bot.command(name='guess', help='Launch the interface for guess submission.')
@is_dm()
async def gather_guess(ctx):

    # Extract information about the user
    user_id = str(ctx.author.id) # As string to avoid DB integer overflows.

    # Connect to the DB
    config = load_config()
    with psycopg2.connect(**config) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Determine if the user is registered to a team:
            sql = """SELECT * FROM solvers JOIN teams ON solvers.team_id = teams.team_id
                WHERE discord_id = %s"""
            data = (user_id,)
            cur.execute(sql, data)
            row = cur.fetchone()

            # Restrict to registered users:
            if row is None:
                await ctx.send('The `!guess` command is only available to registered solvers.\n'
                    'To register, create a team via `!team create` or join a team via `!team join`.')
                return

            # TODO: Gather full team data and pass this along to process_guess()
            num_guesses = row['num_guesses']

            # Refuse to process a guess attempt when the team has 0 guesses left:
            if num_guesses < 1:
                await ctx.send("Your team has run out of guesses. "
                    "To request additional guesses, contact the hunt organizers.")
                return

            # Generate a list of puzzles that the team can select from:
                # TODO: Restrict to unsolved puzzles
            sql = """SELECT puzzle_id, puzzle_name from puzzles ORDER BY puzzle_id ASC"""
            cur.execute(sql)
            puzzle_dict = {row['puzzle_name']: row['puzzle_id'] for row in cur}

            # Launch the data entry user interface:
            view = DropdownView(puzzle_dict, ctx)
            await ctx.send("Please select a puzzle to continue:", view=view)

### RUN SCRIPT #################################################################

bot.run(TOKEN)
