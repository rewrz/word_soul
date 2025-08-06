DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS worlds;
DROP TABLE IF EXISTS game_sessions;

CREATE TABLE users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE worlds (
  world_id INTEGER PRIMARY KEY AUTOINCREMENT,
  creator_id INTEGER NOT NULL,
  world_name TEXT NOT NULL,
  world_blueprint TEXT NOT NULL, -- JSON
  FOREIGN KEY (creator_id) REFERENCES users (user_id)
);

CREATE TABLE game_sessions (
  session_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  world_id INTEGER NOT NULL,
  current_state TEXT NOT NULL, -- JSON
  last_played TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (user_id),
  FOREIGN KEY (world_id) REFERENCES worlds (world_id)
);
