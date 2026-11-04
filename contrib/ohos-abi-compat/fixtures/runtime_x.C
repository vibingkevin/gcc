#include "runtime.h"
#include <cstdlib>

int destroyed = 0;
int runtime_test()
{
  Base *object = create_object();
  if (!dynamic_cast<Derived *>(object) || object->value() != 42)
    std::abort();
  delete object;
  if (destroyed != 1)
    std::abort();
  auto shared = std::make_shared<int>(41);
  consume(std::string(128, 'k'), {1, 2, 3}, shared);
  if (*shared != 42 || shared.use_count() != 1)
    std::abort();
  if (transform(std::string(128, 'k')) != std::string(128, 'k') + "!")
    std::abort();
  try { throw_error(); }
  catch (const std::runtime_error &error) {
    if (std::string(error.what()) == "cross-so")
      return 0;
  }
  return 1;
}
