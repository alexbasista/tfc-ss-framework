output "test0" {
  value = random_pet.test0.id
}

output "test1" {
  value     = random_pet.test1.id
  sensitive = true
}