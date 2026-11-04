#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

struct Base { virtual ~Base(); virtual int value() const = 0; };
struct Derived : Base { ~Derived(); int value() const; };
extern int destroyed;
Base *create_object();
void consume(std::string, std::vector<int>, std::shared_ptr<int>);
std::string transform(std::string);
void throw_error();
int runtime_test();
