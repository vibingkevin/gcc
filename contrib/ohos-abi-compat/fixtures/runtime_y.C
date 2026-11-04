#include "runtime.h"
#include <cstdlib>

Base::~Base() {}
Derived::~Derived() { ++destroyed; }
int Derived::value() const { return 42; }
Base *create_object() { return new Derived; }
void consume(std::string text, std::vector<int> values, std::shared_ptr<int> shared)
{
  if (text != std::string(128, 'k') || values != std::vector<int>({1, 2, 3}))
    std::abort();
  ++*shared;
}
std::string transform(std::string text) { return text + "!"; }
void throw_error() { throw std::runtime_error("cross-so"); }
