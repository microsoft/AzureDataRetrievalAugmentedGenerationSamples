using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace CosmosRecipeGuide
{

    public class VectorSearchDoc
    {

        public string _id { get; set; }
        public List<float> embedding { get; set; }        
    }     


}
