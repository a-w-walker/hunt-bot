import psycopg2
from config import load_config

def create_tables():
    commands = (
        """ DROP TABLE IF EXISTS puzzles, responses, guesslog, solvers, teams CASCADE """,
        """ CREATE TABLE IF NOT EXISTS puzzles (
            puzzle_id SERIAL PRIMARY KEY,
            puzzle_name VARCHAR(255) NOT NULL,
            puzzle_points INTEGER NOT NULL,
            is_final_puzzle BOOLEAN NOT NULL) """,
        """ CREATE TABLE IF NOT EXISTS responses (
            response_id SERIAL PRIMARY KEY,
            puzzle_id INTEGER NOT NULL,
            guess VARCHAR(255),
            is_answer BOOLEAN DEFAULT FALSE,
            response VARCHAR(255) NOT NULL) """,
        """ CREATE TABLE IF NOT EXISTS guesslog (
            guess_id SERIAL PRIMARY KEY,
            puzzle_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            guess VARCHAR(255),
            guess_status VARCHAR(20),
            guess_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP) """,
        """ CREATE TABLE IF NOT EXISTS solvers (
            solver_id SERIAL PRIMARY KEY,
            discord_id VARCHAR(255) NOT NULL,
            discord_name VARCHAR(255) NOT NULL,
            team_id INTEGER NOT NULL,
            is_captain BOOLEAN NOT NULL) """,
        """ CREATE TABLE IF NOT EXISTS teams (
            team_id SERIAL PRIMARY KEY,
            team_name VARCHAR(255) NOT NULL,
            team_token VARCHAR(20) NOT NULL,
            num_guesses INTEGER DEFAULT 50,
            score INTEGER DEFAULT 0,
            is_hunt_solved BOOLEAN DEFAULT FALSE,
            is_deleted BOOLEAN DEFAULT FALSE,
            last_solve_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            hunt_solve_time TIMESTAMP WITH TIME ZONE DEFAULT NULL)""")
    try:
        config = load_config()
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                for command in commands:
                    cur.execute(command)
    except (psycopg2.DatabaseError, Exception) as error:
        print(error)

def populate_tables():
    commands = (
        """ INSERT INTO puzzles (puzzle_name, puzzle_points, is_final_puzzle)
            VALUES ('Example Puzzle 1', 1, FALSE),
                ('Example Puzzle 2', 1, FALSE),
                ('Example Puzzle 3', 1, FALSE),
                ('Example Meta', 1, TRUE) """,
        """ INSERT INTO responses (puzzle_id, guess, is_answer, response)
            VALUES (1, 'answer1', TRUE, 'Correct!'),
                (1, 'keepgoing1', FALSE, 'Keep going!'),
                (2, 'answer2', TRUE, 'Correct!'),
                (2, 'keepgoing2', FALSE, 'Keep going!'),
                (3, 'answer3', TRUE, 'Correct!'),
                (3, 'keepgoing3', FALSE, 'Keep going!'),
                (4, 'metaanswer', TRUE, 'Correct! You've finished the hunt!'),
                (4, 'metakeepgoing', FALSE, 'Keep going!')"""
            )
    try:
        config = load_config()
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                for command in commands:
                    cur.execute(command)
    except (psycopg2.DatabaseError, Exception) as error:
        print(error)

if __name__ == '__main__':
    create_tables()
    populate_tables()
