#pragma once

struct static_key_false {
	int enabled;
};

#define DEFINE_STATIC_KEY_FALSE(name) struct static_key_false name = {0}
#define static_branch_enable(key) do { (key)->enabled = 1; } while (0)
#define static_branch_disable(key) do { (key)->enabled = 0; } while (0)
